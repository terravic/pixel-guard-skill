"""Deterministic multi-pass computer vision preprocessing and multi-frame extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageSequence

from .config import ScanConfig
from .models import PassImage

logger = logging.getLogger("pixel_guard.preprocessor")


@dataclass(frozen=True)
class ExtractedFrame:
    """Native RGBA and white-composited RGB arrays for a distinct container frame."""

    frame_index: int
    raw_rgba: np.ndarray        # uint8 (H, W, 4), preserving uncomposited RGB under alpha=0
    composited_rgb: np.ndarray  # uint8 (H, W, 3), alpha-composited onto opaque white (#FFFFFF)
    has_alpha_channel: bool


def _pil_frame_to_raw_rgba(frame: Image.Image) -> tuple[np.ndarray, bool]:
    """Extract raw RGBA uint8 array without destroying RGB values beneath alpha=0 pixels."""
    mode = frame.mode
    has_alpha = mode in {"RGBA", "LA", "PA"} or (mode == "P" and "transparency" in frame.info)
    if mode == "RGBA":
        rgba = np.array(frame, dtype=np.uint8)
    else:
        converted = frame.convert("RGBA")
        rgba = np.array(converted, dtype=np.uint8)
    return rgba, has_alpha


def composite_rgba_on_white(rgba: np.ndarray) -> np.ndarray:
    """Alpha-composite an RGBA uint8 image onto an opaque #FFFFFF background."""
    alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
    rgb = rgba[:, :, :3].astype(np.float32)
    comp = rgb * alpha + 255.0 * (1.0 - alpha)
    return np.clip(np.rint(comp), 0, 255).astype(np.uint8)


def extract_distinct_frames(image_path: str | Path, config: ScanConfig) -> list[ExtractedFrame]:
    """Iterate container frames, skipping near-identical animation duplicates."""
    frames: list[ExtractedFrame] = []
    prev_gray: np.ndarray | None = None

    with Image.open(image_path) as img:
        for idx, raw_frame in enumerate(ImageSequence.Iterator(img)):
            if len(frames) >= config.max_frames:
                logger.debug("Reached max_frames=%d limit on %s", config.max_frames, image_path)
                break

            rgba, has_alpha = _pil_frame_to_raw_rgba(raw_frame)
            comp_rgb = composite_rgba_on_white(rgba)
            gray = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2GRAY)

            if prev_gray is not None and prev_gray.shape == gray.shape:
                mean_diff = float(np.mean(cv2.absdiff(prev_gray, gray)))
                if mean_diff < config.frame_diff_threshold:
                    continue

            prev_gray = gray
            frames.append(
                ExtractedFrame(
                    frame_index=idx,
                    raw_rgba=rgba,
                    composited_rgb=comp_rgb,
                    has_alpha_channel=has_alpha,
                )
            )

    return frames


def _morphological_deviation(channel: np.ndarray, kernel_size: int = 35) -> np.ndarray:
    """Compute halo-free, bridge-free local stroke deviation |ch - medianBlur(ch)|."""
    k = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
    bg = cv2.medianBlur(channel, k)
    return cv2.absdiff(channel, bg)


def _amplify_deviation_to_ocr_canvas(
    deviation: np.ndarray,
    noise_floor: float = 2.5,
    min_cut: float = 1.5,
) -> np.ndarray:
    """Locally normalize stroke deviations by local peak envelope to preserve anti-aliasing."""
    env_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    local_peak = cv2.dilate(deviation, env_kernel).astype(np.float32)
    denom = np.maximum(local_peak, noise_floor)
    dev_f = deviation.astype(np.float32)
    if min_cut > 0.0:
        dev_f = np.where(dev_f < min_cut, 0.0, dev_f)
    ratio = np.clip(dev_f / denom, 0.0, 1.0)
    return np.clip(np.rint(255.0 * (1.0 - ratio)), 0, 255).astype(np.uint8)


def _extract_micro_text_rois(
    gray: np.ndarray,
    deviation: np.ndarray,
    min_h: int = 2,
    max_h: int = 9,
) -> list[tuple[int, int, int, int]]:
    """Locate horizontal ROI clusters containing micro-glyph connected components (2px-9px tall)."""
    img_h, img_w = gray.shape[:2]
    binary = (deviation >= 3).astype(np.uint8) * 255
    if int(np.count_nonzero(binary)) < 10:
        return []

    # Merge horizontally adjacent micro-characters into word/line blobs
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (16, 3))
    merged = cv2.dilate(binary, horiz_kernel, iterations=1)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)

    rois: list[tuple[int, int, int, int]] = []
    for label_idx in range(1, num_labels):
        x = int(stats[label_idx, cv2.CC_STAT_LEFT])
        y = int(stats[label_idx, cv2.CC_STAT_TOP])
        w = int(stats[label_idx, cv2.CC_STAT_WIDTH])
        h = int(stats[label_idx, cv2.CC_STAT_HEIGHT])

        # Merged height adds up to +2px from the 3px vertical kernel
        if (min_h <= h <= max_h + 3) and w >= 16 and (w / max(1, h)) >= 2.2:
            pad_x = 12
            pad_y = 6
            rx = max(0, x - pad_x)
            ry = max(0, y - pad_y)
            rw = min(img_w - rx, w + 2 * pad_x)
            rh = min(img_h - ry, h + 2 * pad_y)
            rois.append((rx, ry, rw, rh))

    rois.sort(key=lambda r: r[2] * r[3], reverse=True)
    return rois[:6]


def generate_vision_passes(
    frames: list[ExtractedFrame],
    config: ScanConfig,
) -> tuple[list[PassImage], tuple[str, ...]]:
    """Generate smart-gated deterministic CV passes across all distinct frames."""
    passes: list[PassImage] = []
    analyzed_channels: list[str] = ["RGB", "CLAHE", "LAB/HSV", "Alpha", "High-Pass", "Metadata"]

    for frame in frames:
        f_idx = frame.frame_index
        comp_rgb = frame.composited_rgb
        raw_rgba = frame.raw_rgba
        gray = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2GRAY)

        gray_span = int(gray.max()) - int(gray.min())

        # Pass A: Baseline human-visible RGB -> Grayscale (invert dark-mode canvases for LSTM OCR)
        if gray_span >= 15:
            baseline_gray = (255 - gray) if float(np.median(gray)) < 96.0 else gray
            passes.append(
                PassImage(
                    pass_id="baseline",
                    display_label="Pass A (Baseline RGB)",
                    channel_group="RGB",
                    frame_index=f_idx,
                    image=baseline_gray,
                    psm_modes=(6, 11),
                )
            )

        # Pass B: Extreme Low-Contrast Amplification (Local Peak-Normalized Median Deviation)
        if gray_span >= 2:
            deviation = _morphological_deviation(gray, kernel_size=35)
            if int(deviation.max()) >= 2:
                micro_contrast = _amplify_deviation_to_ocr_canvas(deviation, noise_floor=2.5)
                passes.append(
                    PassImage(
                        pass_id="clahe_contrast",
                        display_label="Pass B (Extreme CLAHE & Micro-Contrast Enhancement)",
                        channel_group="CLAHE",
                        frame_index=f_idx,
                        image=micro_contrast,
                        psm_modes=(6, 11),
                    )
                )

                # Pass F: 4x Cubic Super-Resolution ROI Pass for Sub-8px Micro-Text & Edge-Bleed Text
                for rx, ry, rw, rh in _extract_micro_text_rois(
                    gray,
                    deviation,
                    min_h=2,
                    max_h=max(12, config.micro_text_height_px + 4),
                ):
                    roi_dev = deviation[ry : ry + rh, rx : rx + rw]
                    roi_norm = _amplify_deviation_to_ocr_canvas(roi_dev, noise_floor=2.5, min_cut=0.0)
                    scale = 4.0
                    upscaled = cv2.resize(
                        roi_norm,
                        None,
                        fx=scale,
                        fy=scale,
                        interpolation=cv2.INTER_CUBIC,
                    )
                    padded = cv2.copyMakeBorder(upscaled, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
                    passes.append(
                        PassImage(
                            pass_id="micro_upscale",
                            display_label="Pass F (4x Cubic Micro-Text Upscale)",
                            channel_group="High-Pass",
                            frame_index=f_idx,
                            image=padded,
                            scale_factor=scale,
                            offset_x=rx - 5,  # 20px border / 4.0 scale = 5px offset compensation
                            offset_y=ry - 5,
                            psm_modes=(7, 6),
                        )
                    )

        # Pass C: Perceptual Chrominance Channels (CIE LAB a*, b* & HSV Saturation)
        rgb_diff = np.maximum(
            cv2.absdiff(comp_rgb[:, :, 0], comp_rgb[:, :, 1]),
            cv2.absdiff(comp_rgb[:, :, 1], comp_rgb[:, :, 2]),
        )
        if int(rgb_diff.max()) >= 3:
            lab = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2LAB)
            dev_a = _morphological_deviation(lab[:, :, 1], kernel_size=35)
            dev_b = _morphological_deviation(lab[:, :, 2], kernel_size=35)
            hsv = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2HSV)
            dev_s = _morphological_deviation(hsv[:, :, 1], kernel_size=35)
            chroma_dev = np.maximum(np.maximum(dev_a, dev_b), dev_s // 2)
            if int(chroma_dev.max()) >= 3:
                chroma_canvas = _amplify_deviation_to_ocr_canvas(chroma_dev, noise_floor=2.5)
                passes.append(
                    PassImage(
                        pass_id="perceptual_chroma",
                        display_label="Pass C (CIE LAB Chrominance & HSV Saturation Isolation)",
                        channel_group="LAB/HSV",
                        frame_index=f_idx,
                        image=chroma_canvas,
                        psm_modes=(6,),
                    )
                )

        # Pass D: Alpha Channel Isolation (Partial Alpha Perturbation + Zero-Alpha Raw RGB)
        if frame.has_alpha_channel:
            alpha = raw_rgba[:, :, 3]
            alpha_min, alpha_max = int(alpha.min()), int(alpha.max())

            # D1: Partial or modulated alpha mask
            if alpha_max - alpha_min >= 2:
                alpha_dev = _morphological_deviation(alpha, kernel_size=35)
                if int(alpha_dev.max()) >= 2:
                    alpha_mask_canvas = _amplify_deviation_to_ocr_canvas(alpha_dev, noise_floor=2.0)
                    passes.append(
                        PassImage(
                            pass_id="alpha_partial",
                            display_label="Pass D (Alpha Channel Opacity Isolation)",
                            channel_group="Alpha",
                            frame_index=f_idx,
                            image=alpha_mask_canvas,
                            psm_modes=(6, 11),
                        )
                    )

            # D2: Uncomposited raw RGB hidden beneath low/zero alpha (alpha < threshold)
            low_alpha_cutoff = int(round(config.alpha_opacity_threshold * 255.0))
            low_alpha_mask = alpha < low_alpha_cutoff
            if bool(np.any(low_alpha_mask)):
                raw_gray = cv2.cvtColor(raw_rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
                masked_vals = raw_gray[low_alpha_mask]
                if masked_vals.size > 16 and (int(masked_vals.max()) - int(masked_vals.min())) >= 3:
                    bg_fill = int(np.median(masked_vals))
                    isolated_raw = np.where(low_alpha_mask, raw_gray, bg_fill).astype(np.uint8)
                    raw_dev = _morphological_deviation(isolated_raw, kernel_size=35)
                    if int(raw_dev.max()) >= 2:
                        zero_alpha_canvas = _amplify_deviation_to_ocr_canvas(raw_dev, noise_floor=2.5)
                        passes.append(
                            PassImage(
                                pass_id="alpha_zero_rgb",
                                display_label="Pass D (Zero/Low-Alpha Raw RGB Extraction)",
                                channel_group="Alpha",
                                frame_index=f_idx,
                                image=zero_alpha_canvas,
                                psm_modes=(6, 11),
                            )
                        )

        # Pass E: High-Pass Spatial Frequency / Embossed Gradient Enhancement
        if gray_span >= 2:
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            grad_mag = cv2.magnitude(gx, gy)
            p99 = float(np.percentile(grad_mag, 99.5))
            # Only trigger edge OCR when subtle/embossed edges exist that aren't purely flat
            if p99 >= 4.0:
                scaled_edge = np.clip((grad_mag / max(p99, 12.0)) * 255.0, 0.0, 255.0).astype(np.uint8)
                close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                closed_edge = cv2.morphologyEx(scaled_edge, cv2.MORPH_CLOSE, close_k)
                edge_canvas = 255 - closed_edge
                passes.append(
                    PassImage(
                        pass_id="edge_frequency",
                        display_label="Pass E (High-Pass Sobel/Laplacian Frequency Residual)",
                        channel_group="High-Pass",
                        frame_index=f_idx,
                        image=edge_canvas,
                        psm_modes=(6,),
                    )
                )

    return passes, tuple(analyzed_channels)
