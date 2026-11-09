"""WCAG 2.1 relative luminance contrast, CIEDE2000 perceptual color difference, and collar sampling."""

from __future__ import annotations

import math

import cv2
import numpy as np

from .config import ScanConfig
from .models import DetectedRegion, VisibilityProfile
from .preprocessor import ExtractedFrame

try:
    from skimage.color import deltaE_ciede2000 as _skimage_ciede2000  # type: ignore[import-untyped]
    from skimage.color import rgb2lab as _skimage_rgb2lab  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    _skimage_ciede2000 = None
    _skimage_rgb2lab = None


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """Format an 8-bit (R, G, B) tuple as uppercase #RRGGBB."""
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def compute_relative_luminance(rgb: tuple[int, int, int] | np.ndarray) -> float:
    """Compute WCAG 2.1 relative luminance L in [0.0, 1.0] from 8-bit sRGB."""
    arr = np.asarray(rgb, dtype=np.float64) / 255.0
    linear = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])


def calculate_wcag_contrast(fg_rgb: tuple[int, int, int], bg_rgb: tuple[int, int, int]) -> float:
    """Compute WCAG 2.1 contrast ratio CR in [1.0, 21.0]."""
    l1 = compute_relative_luminance(fg_rgb)
    l2 = compute_relative_luminance(bg_rgb)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return float((lighter + 0.05) / (darker + 0.05))


def rgb_to_cielab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Convert an 8-bit sRGB triplet to CIE 1976 L*a*b* (D65 illuminant)."""
    if _skimage_rgb2lab is not None:
        sample = np.array([[rgb]], dtype=np.uint8) / 255.0
        lab = _skimage_rgb2lab(sample)[0, 0]
        return (float(lab[0]), float(lab[1]), float(lab[2]))

    # Exact sRGB -> XYZ (D65) -> LAB fallback
    srgb = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    x = lin[0] * 0.4124564 + lin[1] * 0.3575761 + lin[2] * 0.1804375
    y = lin[0] * 0.2126729 + lin[1] * 0.7151522 + lin[2] * 0.0721750
    z = lin[0] * 0.0193339 + lin[1] * 0.1191920 + lin[2] * 0.9503041

    xr, yr, zr = x / 0.95047, y / 1.00000, z / 1.08883
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    fx = xr ** (1.0 / 3.0) if xr > eps else (kappa * xr + 16.0) / 116.0
    fy = yr ** (1.0 / 3.0) if yr > eps else (kappa * yr + 16.0) / 116.0
    fz = zr ** (1.0 / 3.0) if zr > eps else (kappa * zr + 16.0) / 116.0

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return (float(L), float(a), float(b))


def calculate_ciede2000(fg_rgb: tuple[int, int, int], bg_rgb: tuple[int, int, int]) -> float:
    """Compute perceptual CIEDE2000 color difference (Delta E_00) between two sRGB colors."""
    lab1 = rgb_to_cielab(fg_rgb)
    lab2 = rgb_to_cielab(bg_rgb)
    if _skimage_ciede2000 is not None:
        val = _skimage_ciede2000(np.array([lab1]), np.array([lab2]))[0]
        return float(val)

    # Exact Sharma-Wu-Dalal (2005) CIEDE2000 formula
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    C_bar = 0.5 * (C1 + C2)
    C_bar7 = C_bar**7
    G = 0.5 * (1.0 - math.sqrt(C_bar7 / (C_bar7 + 25.0**7)))
    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2
    C1p = math.hypot(a1p, b1)
    C2p = math.hypot(a2p, b2)

    h1p = 0.0 if C1p == 0.0 else (math.degrees(math.atan2(b1, a1p)) % 360.0)
    h2p = 0.0 if C2p == 0.0 else (math.degrees(math.atan2(b2, a2p)) % 360.0)

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0.0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0

    dHp = 2.0 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp * 0.5))
    Lp_bar = 0.5 * (L1 + L2)
    Cp_bar = 0.5 * (C1p + C2p)

    if C1p * C2p == 0.0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hp_bar = 0.5 * (h1p + h2p)
    elif h1p + h2p < 360.0:
        hp_bar = 0.5 * (h1p + h2p + 360.0)
    else:
        hp_bar = 0.5 * (h1p + h2p - 360.0)

    T = (
        1.0
        - 0.17 * math.cos(math.radians(hp_bar - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * hp_bar))
        + 0.32 * math.cos(math.radians(3.0 * hp_bar + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * hp_bar - 63.0))
    )
    d_theta = 30.0 * math.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    Cp_bar7 = Cp_bar**7
    RC = 2.0 * math.sqrt(Cp_bar7 / (Cp_bar7 + 25.0**7))
    SL = 1.0 + (0.015 * ((Lp_bar - 50.0) ** 2)) / math.sqrt(20.0 + ((Lp_bar - 50.0) ** 2))
    SC = 1.0 + 0.045 * Cp_bar
    SH = 1.0 + 0.015 * Cp_bar * T
    RT = -math.sin(math.radians(2.0 * d_theta)) * RC

    term_L = dLp / SL
    term_C = dCp / SC
    term_H = dHp / SH
    return float(math.sqrt(term_L**2 + term_C**2 + term_H**2 + RT * term_C * term_H))


def _segment_glyph_and_collar_masks(
    comp_rgb_crop: np.ndarray,
    pass_crop_gray: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Segment foreground glyph mask and 3px dilated local background collar without polarity inversion."""
    h, w = comp_rgb_crop.shape[:2]
    if pass_crop_gray is not None and pass_crop_gray.size > 0:
        if pass_crop_gray.shape[:2] != (h, w):
            guide = cv2.resize(pass_crop_gray, (w, h), interpolation=cv2.INTER_LINEAR)
        else:
            guide = pass_crop_gray
    else:
        guide = cv2.cvtColor(comp_rgb_crop, cv2.COLOR_RGB2GRAY)

    _, otsu = cv2.threshold(guide, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Perimeter rim anchor: background dominates the outer 1-pixel bounding-box rim
    rim_pixels = np.concatenate([
        otsu[0, :],
        otsu[-1, :],
        otsu[:, 0],
        otsu[:, -1],
    ])
    bg_is_white = float(np.mean(rim_pixels)) >= 127.5
    fg_mask = (otsu == 0) if bg_is_white else (otsu == 255)

    # Fallback if Otsu degenerated on ultra-flat region
    if not np.any(fg_mask) or np.all(fg_mask):
        gray = cv2.cvtColor(comp_rgb_crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
        rim_gray = float(np.median(np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])))
        diff = np.abs(gray - rim_gray)
        cutoff = max(0.5, float(np.percentile(diff, 70)))
        fg_mask = diff >= cutoff

    fg_u8 = fg_mask.astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dilated = cv2.dilate(fg_u8, kernel, iterations=3)
    collar_mask = (dilated > 0) & (~fg_mask)

    if not np.any(collar_mask):
        collar_mask = ~fg_mask

    return fg_mask, collar_mask


def profile_region_visibility(
    region: DetectedRegion,
    frame: ExtractedFrame,
    config: ScanConfig,
) -> VisibilityProfile:
    """Compute foreground/collar colors, WCAG CR, CIEDE2000 Delta-E, alpha, and anomaly flags."""
    img_h, img_w = frame.composited_rgb.shape[:2]
    x, y, w, h = region.bbox

    pad = 4
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(img_w, x + w + pad)
    y1 = min(img_h, y + h + pad)

    # For zero-alpha RGB steganography, human eyes see uniform white/transparent canvas (CR = 1.0),
    # while raw_rgba holds the hidden RGB text.
    comp_crop = frame.composited_rgb[y0:y1, x0:x1]
    rgba_crop = frame.raw_rgba[y0:y1, x0:x1]

    fg_mask, collar_mask = _segment_glyph_and_collar_masks(comp_crop, region.pass_crop_gray)

    if np.any(fg_mask):
        fg_med = np.median(comp_crop[fg_mask], axis=0)
        fg_rgb = (int(round(fg_med[0])), int(round(fg_med[1])), int(round(fg_med[2])))
        raw_alphas = rgba_crop[:, :, 3][fg_mask].astype(np.float32) / 255.0
        mean_alpha = float(np.mean(raw_alphas))
    else:
        fg_rgb = (255, 255, 255)
        mean_alpha = 1.0

    if np.any(collar_mask):
        bg_med = np.median(comp_crop[collar_mask], axis=0)
        bg_rgb = (int(round(bg_med[0])), int(round(bg_med[1])), int(round(bg_med[2])))
    else:
        bg_rgb = (255, 255, 255)

    # If partial alpha existed on a transparent canvas, mean_alpha reflects actual glyph alpha
    if frame.has_alpha_channel and region.origin_pass in {"alpha_partial", "alpha_zero_rgb"}:
        # Check whether canvas had low alpha vs high alpha modulated slightly
        collar_alpha = float(np.mean(rgba_crop[:, :, 3][collar_mask])) / 255.0 if np.any(collar_mask) else 1.0
        if region.origin_pass == "alpha_zero_rgb":
            # Measure alpha strictly on pixels where raw RGB deviated inside low-alpha zone
            low_a = rgba_crop[:, :, 3] < int(round(config.alpha_opacity_threshold * 255))
            if np.any(low_a):
                mean_alpha = float(np.mean(rgba_crop[:, :, 3][low_a])) / 255.0
        elif abs(mean_alpha - collar_alpha) < 0.25 and mean_alpha > 0.7:
            # Subtle alpha carving on mostly opaque layer (e.g. alpha=248 on 255)
            mean_alpha = abs(mean_alpha - collar_alpha)

    contrast_ratio = calculate_wcag_contrast(fg_rgb, bg_rgb)
    delta_e = calculate_ciede2000(fg_rgb, bg_rgb)
    fg_lab = rgb_to_cielab(fg_rgb)
    bg_lab = rgb_to_cielab(bg_rgb)

    flags: list[str] = []
    if contrast_ratio < config.wcag_contrast_threshold:
        flags.append("LOW_CONTRAST_CAMOUFLAGE")
    if delta_e < config.ciede2000_delta_e_threshold:
        flags.append("SUB_JND_COLOR_DELTA")
    if (frame.has_alpha_channel and mean_alpha < config.alpha_opacity_threshold) or region.origin_pass in {
        "alpha_partial",
        "alpha_zero_rgb",
    }:
        flags.append("ALPHA_TRANSPARENCY_CAMOUFLAGE")
    if h < config.micro_text_height_px:
        flags.append("MICRO_TEXT_ANOMALY")
    if region.origin_pass == "edge_frequency":
        flags.append("FREQUENCY_EDGE_CAMOUFLAGE")
    if region.origin_pass == "perceptual_chroma":
        flags.append("CHROMINANCE_CAMOUFLAGE")
    if region.frame_index > 0:
        flags.append("INACTIVE_FRAME_OBFUSCATION")

    # Margin bleed anomaly: flush within <= 6px of outer canvas border with compact glyph height (<= 14px)
    near_margin = (x <= 6) or (y <= 6) or ((x + w) >= img_w - 6) or ((y + h) >= img_h - 6)
    if near_margin and h <= 14:
        flags.append("MARGIN_BLEED_PLACEMENT")

    if region.origin_pass == "micro_upscale" and "MICRO_TEXT_ANOMALY" not in flags and "MARGIN_BLEED_PLACEMENT" not in flags:
        flags.append("MICRO_TEXT_ANOMALY")

    # Any text NOT legible in Pass A ('baseline') is non-visible by definition
    if region.origin_pass != "baseline" and not flags:
        flags.append("ENHANCED_PASS_ONLY_RECOVERY")

    is_visible = (
        region.origin_pass == "baseline"
        and region.frame_index == 0
        and len(flags) == 0
    )

    return VisibilityProfile(
        contrast_ratio=contrast_ratio,
        delta_e=delta_e,
        mean_alpha=mean_alpha,
        font_height_px=h,
        foreground_rgb=fg_rgb,
        background_rgb=bg_rgb,
        foreground_hex=rgb_to_hex(fg_rgb),
        background_hex=rgb_to_hex(bg_rgb),
        foreground_lab=fg_lab,
        background_lab=bg_lab,
        is_human_visible=is_visible,
        anomaly_flags=tuple(dict.fromkeys(flags)),
    )
