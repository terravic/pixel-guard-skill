"""Unit tests for WCAG 2.1 relative luminance, CIEDE2000 Delta-E, and collar visibility profiling."""

from __future__ import annotations

import numpy as np
import pytest

from pixel_guard.color_science import (
    calculate_ciede2000,
    calculate_wcag_contrast,
    compute_relative_luminance,
    profile_region_visibility,
    rgb_to_cielab,
    rgb_to_hex,
)
from pixel_guard.config import ScanConfig
from pixel_guard.models import DetectedRegion
from pixel_guard.preprocessor import ExtractedFrame


def test_wcag_luminance_and_contrast_extremes() -> None:
    """Verify exact sRGB relative luminance and WCAG 2.1 contrast ratios."""
    assert compute_relative_luminance((0, 0, 0)) == pytest.approx(0.0, abs=1e-6)
    assert compute_relative_luminance((255, 255, 255)) == pytest.approx(1.0, abs=1e-6)
    assert calculate_wcag_contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=1e-4)
    assert calculate_wcag_contrast((128, 128, 128), (128, 128, 128)) == pytest.approx(1.0, abs=1e-6)

    # Off-white (#FAFAFA) on pure white (#FFFFFF) must be < 1.06:1
    cr_camo = calculate_wcag_contrast((250, 250, 250), (255, 255, 255))
    assert 1.0 < cr_camo < 1.06


def test_ciede2000_color_difference_scale() -> None:
    """Verify CIEDE2000 Delta-E distinguishes imperceptible vs high-contrast pairs."""
    assert calculate_ciede2000((255, 255, 255), (255, 255, 255)) == pytest.approx(0.0, abs=1e-6)

    de_camo = calculate_ciede2000((250, 250, 250), (255, 255, 255))
    assert 0.5 < de_camo < 2.5

    de_strong = calculate_ciede2000((15, 15, 15), (255, 255, 255))
    assert de_strong > 80.0

    lab_white = rgb_to_cielab((255, 255, 255))
    assert lab_white[0] == pytest.approx(100.0, abs=0.1)
    assert rgb_to_hex((13, 148, 136)) == "#0D9488"


def test_profile_region_visibility_flags_low_contrast_and_micro_text() -> None:
    """Verify collar sampling accurately extracts stroke and background colors without inversion."""
    cfg = ScanConfig()
    # Construct synthetic 120x60 white canvas with a #FAFAFA horizontal bar representing strokes
    rgba = np.full((60, 120, 4), 255, dtype=np.uint8)
    rgba[22:36, 20:95, :3] = 250
    comp_rgb = rgba[:, :, :3].copy()

    pass_guide = np.full((22, 83), 255, dtype=np.uint8)
    pass_guide[4:18, 4:79] = 0

    frame = ExtractedFrame(
        frame_index=0,
        raw_rgba=rgba,
        composited_rgb=comp_rgb,
        has_alpha_channel=False,
    )
    region = DetectedRegion(
        text="hidden test",
        bbox=(20, 22, 75, 14),
        confidence=0.92,
        origin_pass="clahe_contrast",
        display_method="Pass B",
        frame_index=0,
        pass_crop_gray=pass_guide,
    )

    profile = profile_region_visibility(region, frame, cfg)
    assert not profile.is_human_visible
    assert profile.contrast_ratio < 1.1
    assert "LOW_CONTRAST_CAMOUFLAGE" in profile.anomaly_flags
    assert "SUB_JND_COLOR_DELTA" in profile.anomaly_flags

    micro_region = DetectedRegion(
        text="tiny",
        bbox=(10, 10, 40, 5),
        confidence=0.80,
        origin_pass="micro_upscale",
        display_method="Pass F",
        frame_index=0,
    )
    micro_profile = profile_region_visibility(micro_region, frame, cfg)
    assert "MICRO_TEXT_ANOMALY" in micro_profile.anomaly_flags
