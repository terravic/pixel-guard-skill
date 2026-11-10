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
    """Native RGBA and white-composited RGB arrays for a distinct container page or frame."""

    frame_index: int
    raw_rgba: np.ndarray        # uint8 (H, W, 4), preserving uncomposited RGB under alpha=0
    composited_rgb: np.ndarray  # uint8 (H, W, 3), alpha-composited onto opaque white (#FFFFFF)
    has_alpha_channel: bool
    is_document_page: bool = False


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
    """Iterate container pages/frames, preserving all TIFF pages and skipping identical animation holds."""
    frames: list[ExtractedFrame] = []
    prev_gray: np.ndarray | None = None

    with Image.open(image_path) as img:
        is_tiff = (getattr(img, "format", "") or "").upper() == "TIFF"
        for idx, raw_frame in enumerate(ImageSequence.Iterator(img)):
            if len(frames) >= config.max_frames:
                logger.debug("Reached max_frames=%d limit on %s", config.max_frames, image_path)
                break

            rgba, has_alpha = _pil_frame_to_raw_rgba(raw_frame)
            comp_rgb = composite_rgba_on_white(rgba)
            gray = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2GRAY)

            if not is_tiff and prev_gray is not None and prev_gray.shape == gray.shape:
                diff_arr = cv2.absdiff(prev_gray, gray)
                mean_diff = float(np.mean(diff_arr))
                if mean_diff < config.frame_diff_threshold and int(diff_arr.max()) < 3:
                    continue

            prev_gray = gray
            frames.append(
                ExtractedFrame(
                    frame_index=idx,
                    raw_rgba=rgba,
                    composited_rgb=comp_rgb,
                    has_alpha_channel=has_alpha,
                    is_document_page=is_tiff,
                )
            )

    return frames


def _morphological_deviation(channel: np.ndarray, kernel_size: int = 35) -> np.ndarray:
    """Compute halo-free, bridge-free local stroke deviation |ch - medianBlur(ch)|."""
    h, w = channel.shape[:2]
    if h * w >= 900_000 and kernel_size >= 31:
        half_k = max(3, (kernel_size // 2) | 1)
        small = cv2.resize(channel, (max(1, w // 2), max(1, h // 2)), interpolation=cv2.INTER_AREA)
        small_bg = cv2.medianBlur(small, half_k)
        bg = cv2.resize(small_bg, (w, h), interpolation=cv2.INTER_LINEAR)
        return cv2.absdiff(channel, bg)
    k = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
    bg = cv2.medianBlur(channel, k)
    return cv2.absdiff(channel, bg)


def _amplify_deviation_to_ocr_surface(
    deviation: np.ndarray,
    noise_floor: float = 2.5,
    min_cut: float = 1.5,
    envelope_source: np.ndarray | None = None,
) -> np.ndarray:
    """Locally normalize stroke deviations by local peak envelope to preserve anti-aliasing."""
    env_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    peak_input = envelope_source if envelope_source is not None else deviation
    local_peak = cv2.dilate(peak_input, env_kernel).astype(np.float32)
    denom = np.maximum(local_peak, noise_floor)
    dev_f = deviation.astype(np.float32)
    if min_cut > 0.0:
        dev_f = np.where(dev_f < min_cut, 0.0, dev_f)
    ratio = np.clip(dev_f / denom, 0.0, 1.0)
    return np.clip(np.rint(255.0 * (1.0 - ratio)), 0, 255).astype(np.uint8)


def _despeckle_deviation(
    deviation: np.ndarray,
    min_val: int = 3,
    min_area: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    """Suppress isolated sub-glyph noise speckles while preserving anti-aliased stroke halos."""
    seed_bin = (deviation >= min_val).astype(np.uint8) * 255
    nz = int(np.count_nonzero(seed_bin))
    if nz < min_area:
        empty = np.zeros_like(deviation, dtype=np.uint8)
        return empty, empty

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(seed_bin, connectivity=8)
    if num_labels <= 1:
        empty = np.zeros_like(deviation, dtype=np.uint8)
        return empty, empty

    areas = stats[:, cv2.CC_STAT_AREA]
    valid_lut = (areas >= min_area).astype(np.uint8) * 255
    valid_lut[0] = 0
    clean_bin = valid_lut[labels]
    if int(np.count_nonzero(clean_bin)) < min_area:
        empty = np.zeros_like(deviation, dtype=np.uint8)
        return empty, empty

    halo_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    halo_mask = cv2.dilate(clean_bin, halo_k, iterations=1)
    cleaned_dev = np.where(halo_mask > 0, deviation, 0).astype(np.uint8)
    return cleaned_dev, clean_bin


def _merge_overlapping_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Iteratively merge overlapping or touching (x, y, w, h) rectangles."""
    if len(boxes) <= 1:
        return boxes
    rects = [[x, y, x + w, y + h] for x, y, w, h in boxes]
    changed = True
    while changed:
        changed = False
        merged: list[list[int]] = []
        used = [False] * len(rects)
        for i in range(len(rects)):
            if used[i]:
                continue
            ax0, ay0, ax1, ay1 = rects[i]
            for j in range(i + 1, len(rects)):
                if used[j]:
                    continue
                bx0, by0, bx1, by1 = rects[j]
                if not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0):
                    ax0 = min(ax0, bx0)
                    ay0 = min(ay0, by0)
                    ax1 = max(ax1, bx1)
                    ay1 = max(ay1, by1)
                    used[j] = True
                    changed = True
            merged.append([ax0, ay0, ax1, ay1])
        rects = merged
    out = [(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in rects]
    out.sort(key=lambda b: (b[1], b[0]))
    return out


def _build_anomaly_pass_images(
    surface: np.ndarray,
    clean_bin: np.ndarray,
    work_scale: float,
    pass_id: str,
    display_label: str,
    channel_group: str,
    frame_index: int,
    psm_modes: tuple[int, ...],
) -> list[PassImage]:
    """Emit tight ROI-cropped PassImages around surviving anomaly clusters or skip empty passes."""
    if int(np.count_nonzero(clean_bin)) < 10:
        return []

    work_h, work_w = surface.shape[:2]
    horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (28, 7))
    merged = cv2.dilate(clean_bin, horiz_k, iterations=1)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)

    raw_boxes: list[tuple[int, int, int, int]] = []
    for idx in range(1, num_labels):
        x = int(stats[idx, cv2.CC_STAT_LEFT])
        y = int(stats[idx, cv2.CC_STAT_TOP])
        w = int(stats[idx, cv2.CC_STAT_WIDTH])
        h = int(stats[idx, cv2.CC_STAT_HEIGHT])
        if w >= 14 and h >= 4:
            pad_x = 18
            pad_y = 12
            bx = max(0, x - pad_x)
            by = max(0, y - pad_y)
            bw = min(work_w - bx, w + 2 * pad_x)
            bh = min(work_h - by, h + 2 * pad_y)
            raw_boxes.append((bx, by, bw, bh))

    if not raw_boxes:
        return []

    boxes = _merge_overlapping_boxes(raw_boxes)
    total_box_area = sum(bw * bh for _, _, bw, bh in boxes)
    if len(boxes) <= 6 and total_box_area < int(0.50 * work_w * work_h):
        border = 12
        roi_passes: list[PassImage] = []
        roi_psms = (6, 11) if (len(boxes) == 1 and 11 in psm_modes) else (6,)
        for bx, by, bw, bh in boxes:
            crop = surface[by : by + bh, bx : bx + bw]
            padded = cv2.copyMakeBorder(
                crop,
                border,
                border,
                border,
                border,
                cv2.BORDER_CONSTANT,
                value=255,
            )
            roi_passes.append(
                PassImage(
                    pass_id=pass_id,
                    display_label=display_label,
                    channel_group=channel_group,
                    frame_index=frame_index,
                    image=padded,
                    scale_factor=work_scale,
                    offset_x=int(round((bx - border) / work_scale)),
                    offset_y=int(round((by - border) / work_scale)),
                    psm_modes=roi_psms,
                )
            )
        return roi_passes

    return [
        PassImage(
            pass_id=pass_id,
            display_label=display_label,
            channel_group=channel_group,
            frame_index=frame_index,
            image=surface,
            scale_factor=work_scale,
            psm_modes=psm_modes,
        )
    ]


def _extract_micro_text_rois(
    gray: np.ndarray,
    deviation: np.ndarray,
    min_h: int = 2,
    max_h: int = 9,
) -> list[tuple[int, int, int, int]]:
    """Locate horizontal ROI clusters containing micro-glyph connected components (2px-9px tall)."""
    img_h, img_w = gray.shape[:2]
    _, binary = _despeckle_deviation(deviation, min_val=10, min_area=3)
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
        orig_h, orig_w = comp_rgb.shape[:2]
        native_gray = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2GRAY)
        gray_span = int(native_gray.max()) - int(native_gray.min())

        # Downscale oversized full-frame passes to config.max_ocr_dimension while mapping bboxes back to 1x
        max_dim = max(orig_h, orig_w)
        work_scale = min(1.0, float(config.max_ocr_dimension) / float(max_dim)) if max_dim > 0 else 1.0
        if work_scale < 1.0:
            work_w = max(1, int(round(orig_w * work_scale)))
            work_h = max(1, int(round(orig_h * work_scale)))
            work_rgb = cv2.resize(comp_rgb, (work_w, work_h), interpolation=cv2.INTER_AREA)
            work_rgba = cv2.resize(raw_rgba, (work_w, work_h), interpolation=cv2.INTER_AREA)
            work_gray = cv2.cvtColor(work_rgb, cv2.COLOR_RGB2GRAY)
            work_dev = _morphological_deviation(work_gray, kernel_size=35) if gray_span >= 2 else None
            native_dev = _morphological_deviation(native_gray, kernel_size=35) if (gray_span >= 2 and max_dim <= 4096) else None
        else:
            work_rgb = comp_rgb
            work_rgba = raw_rgba
            work_gray = native_gray
            work_dev = _morphological_deviation(work_gray, kernel_size=35) if gray_span >= 2 else None
            native_dev = work_dev

        # Pass A scheduled first so ThreadPoolExecutor starts full-frame baseline OCR immediately
        if gray_span >= 15:
            baseline_gray = (255 - work_gray) if float(np.median(work_gray)) < 96.0 else work_gray
            passes.append(
                PassImage(
                    pass_id="baseline",
                    display_label="Pass A (Baseline RGB)",
                    channel_group="RGB",
                    frame_index=f_idx,
                    image=baseline_gray,
                    scale_factor=work_scale,
                    psm_modes=(6, 11),
                )
            )

        # Pass F runs on native 1x pixels to preserve sub-8px micro-typography and flush border text
        if native_dev is not None and int(native_dev.max()) >= 10:
            for rx, ry, rw, rh in _extract_micro_text_rois(
                native_gray,
                native_dev,
                min_h=2,
                max_h=max(12, config.micro_text_height_px + 4),
            ):
                roi_dev = native_dev[ry : ry + rh, rx : rx + rw]
                roi_norm = _amplify_deviation_to_ocr_surface(roi_dev, noise_floor=2.5, min_cut=0.0)
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

        # Build high-contrast visible-stroke masks (covering 8x8 DCT ringing halos) so enhanced passes focus on subtle anomalies
        if work_dev is not None:
            vis_raw = (work_dev >= 40).astype(np.uint8) * 255
            if bool(np.any(vis_raw)):
                vis_stroke_mask = cv2.dilate(
                    vis_raw,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (13, 13)),
                    iterations=1,
                ) > 0
                vis_edge_mask = cv2.dilate(
                    vis_raw,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)),
                    iterations=1,
                ) > 0
            else:
                vis_stroke_mask = None
                vis_edge_mask = None
        else:
            vis_stroke_mask = None
            vis_edge_mask = None

        # Pass B: Local Median & Micro-Contrast Amplification (Local Peak-Normalized Deviation)
        if work_dev is not None and int(work_dev.max()) >= 2:
            subtle_dev = np.where(vis_stroke_mask, 0, work_dev) if vis_stroke_mask is not None else work_dev
            cleaned_dev, clean_bin = _despeckle_deviation(subtle_dev, min_val=3, min_area=6)
            if int(cleaned_dev.max()) >= 3:
                micro_contrast = _amplify_deviation_to_ocr_surface(
                    cleaned_dev,
                    noise_floor=2.5,
                    envelope_source=work_dev,
                )
                active_bin = np.where(micro_contrast <= 220, clean_bin, 0).astype(np.uint8)
                passes.extend(
                    _build_anomaly_pass_images(
                        surface=micro_contrast,
                        clean_bin=active_bin,
                        work_scale=work_scale,
                        pass_id="clahe_contrast",
                        display_label="Pass B (Local Median & Micro-Contrast Enhancement)",
                        channel_group="CLAHE",
                        frame_index=f_idx,
                        psm_modes=(6, 11),
                    )
                )

        # Pass C: Perceptual Chrominance Channels (CIE LAB a*, b* & HSV Saturation)
        rgb_diff = np.maximum(
            cv2.absdiff(work_rgb[:, :, 0], work_rgb[:, :, 1]),
            cv2.absdiff(work_rgb[:, :, 1], work_rgb[:, :, 2]),
        )
        if int(rgb_diff.max()) >= 3:
            lab = cv2.cvtColor(work_rgb, cv2.COLOR_RGB2LAB)
            dev_a = _morphological_deviation(lab[:, :, 1], kernel_size=35)
            dev_b = _morphological_deviation(lab[:, :, 2], kernel_size=35)
            hsv = cv2.cvtColor(work_rgb, cv2.COLOR_RGB2HSV)
            dev_s = _morphological_deviation(hsv[:, :, 1], kernel_size=35)
            raw_chroma_dev = np.maximum(np.maximum(dev_a, dev_b), dev_s // 2)
            chroma_dev = np.where(vis_stroke_mask, 0, raw_chroma_dev) if vis_stroke_mask is not None else raw_chroma_dev
            cleaned_chroma, chroma_bin = _despeckle_deviation(chroma_dev, min_val=3, min_area=5)
            if int(cleaned_chroma.max()) >= 3:
                chroma_surface = _amplify_deviation_to_ocr_surface(
                    cleaned_chroma,
                    noise_floor=2.5,
                    envelope_source=raw_chroma_dev,
                )
                active_chroma_bin = np.where(chroma_surface <= 220, chroma_bin, 0).astype(np.uint8)
                passes.extend(
                    _build_anomaly_pass_images(
                        surface=chroma_surface,
                        clean_bin=active_chroma_bin,
                        work_scale=work_scale,
                        pass_id="perceptual_chroma",
                        display_label="Pass C (CIE LAB Chrominance & HSV Saturation Isolation)",
                        channel_group="LAB/HSV",
                        frame_index=f_idx,
                        psm_modes=(6,),
                    )
                )

        # Pass D: Alpha Channel Isolation (Partial Alpha Perturbation + Zero-Alpha Raw RGB)
        if frame.has_alpha_channel:
            alpha = work_rgba[:, :, 3]
            alpha_min, alpha_max = int(alpha.min()), int(alpha.max())

            # D1: Partial or modulated alpha mask
            if alpha_max - alpha_min >= 2:
                alpha_dev = _morphological_deviation(alpha, kernel_size=35)
                cleaned_alpha, alpha_bin = _despeckle_deviation(alpha_dev, min_val=2, min_area=4)
                if int(cleaned_alpha.max()) >= 2:
                    alpha_mask_surface = _amplify_deviation_to_ocr_surface(cleaned_alpha, noise_floor=2.0)
                    passes.extend(
                        _build_anomaly_pass_images(
                            surface=alpha_mask_surface,
                            clean_bin=alpha_bin,
                            work_scale=work_scale,
                            pass_id="alpha_partial",
                            display_label="Pass D (Alpha Channel Opacity Isolation)",
                            channel_group="Alpha",
                            frame_index=f_idx,
                            psm_modes=(6, 11),
                        )
                    )

            # D2: Uncomposited raw RGB hidden beneath low/zero alpha (alpha < threshold)
            low_alpha_cutoff = int(round(config.alpha_opacity_threshold * 255.0))
            low_alpha_mask = alpha < low_alpha_cutoff
            if bool(np.any(low_alpha_mask)):
                raw_gray = cv2.cvtColor(work_rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
                masked_vals = raw_gray[low_alpha_mask]
                if masked_vals.size > 16 and (int(masked_vals.max()) - int(masked_vals.min())) >= 3:
                    bg_fill = int(np.median(masked_vals))
                    isolated_raw = np.where(low_alpha_mask, raw_gray, bg_fill).astype(np.uint8)
                    raw_dev = _morphological_deviation(isolated_raw, kernel_size=35)
                    cleaned_raw, raw_bin = _despeckle_deviation(raw_dev, min_val=2, min_area=4)
                    if int(cleaned_raw.max()) >= 2:
                        zero_alpha_surface = _amplify_deviation_to_ocr_surface(cleaned_raw, noise_floor=2.5)
                        passes.extend(
                            _build_anomaly_pass_images(
                                surface=zero_alpha_surface,
                                clean_bin=raw_bin,
                                work_scale=work_scale,
                                pass_id="alpha_zero_rgb",
                                display_label="Pass D (Zero/Low-Alpha Raw RGB Extraction)",
                                channel_group="Alpha",
                                frame_index=f_idx,
                                psm_modes=(6, 11),
                            )
                        )

        # Pass E: High-Pass Spatial Frequency / Embossed Gradient Enhancement
        if gray_span >= 2:
            gx = cv2.Sobel(work_gray, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(work_gray, cv2.CV_32F, 0, 1, ksize=3)
            grad_mag = cv2.magnitude(gx, gy)
            if vis_edge_mask is not None:
                grad_mag = np.where(vis_edge_mask, 0.0, grad_mag)
            p99 = float(np.percentile(grad_mag, 99.5))
            max_grad = float(grad_mag.max())
            # Trigger edge OCR when coherent embossed/outline edges exist above sensor noise
            if max_grad >= 24.0 and (p99 >= 4.0 or max_grad >= 28.0):
                denom = max(p99, 16.0)
                scaled_edge = np.clip((grad_mag / denom) * 255.0, 0.0, 255.0).astype(np.uint8)
                cleaned_edge, edge_bin = _despeckle_deviation(scaled_edge, min_val=110, min_area=12)
                if int(cleaned_edge.max()) >= 110:
                    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                    closed_edge = cv2.morphologyEx(cleaned_edge, cv2.MORPH_CLOSE, close_k)
                    edge_surface = 255 - closed_edge
                    passes.extend(
                        _build_anomaly_pass_images(
                            surface=edge_surface,
                            clean_bin=edge_bin,
                            work_scale=work_scale,
                            pass_id="edge_frequency",
                            display_label="Pass E (High-Pass Sobel/Laplacian Frequency Residual)",
                            channel_group="High-Pass",
                            frame_index=f_idx,
                            psm_modes=(6,),
                        )
                    )

    return passes, tuple(analyzed_channels)
