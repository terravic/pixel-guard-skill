"""End-to-end system tests covering all 37 multi-instance synthetic fixtures, CLI exit codes, and performance budgets."""

from __future__ import annotations

import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

from pixel_guard import ValidationError, scan_image
from tests.generate_test_images import SCENARIO_CATALOG, FixtureSpec


@pytest.mark.parametrize("spec", SCENARIO_CATALOG, ids=[s.key for s in SCENARIO_CATALOG])
def test_all_37_synthetic_tampering_and_control_scenarios(
    spec: FixtureSpec,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Validate every individual synthetic control, tampering instance, and corrupt/polyglot image."""
    target_path = synthetic_fixtures[spec.key]
    assert target_path.is_file(), f"Missing generated fixture on disk: {target_path}"

    if spec.expect_validation_error:
        with pytest.raises(ValidationError):
            scan_image(target_path)
        return

    report = scan_image(target_path)
    assert report.scan_status in spec.expected_statuses, (
        f"[{spec.key}] ({spec.tampering_instance}) status={report.scan_status}, expected={spec.expected_statuses}"
    )
    assert report.visible_count >= spec.expect_visible_min, (
        f"[{spec.key}] visible_count={report.visible_count} < {spec.expect_visible_min}"
    )
    assert report.quarantined_count >= spec.expect_quarantined_min, (
        f"[{spec.key}] quarantined_count={report.quarantined_count} < {spec.expect_quarantined_min}"
    )

    if spec.expect_quarantined_min == 0:
        assert report.quarantined_count == 0, (
            f"[{spec.key}] clean control unexpectedly quarantined: {report.section_2_quarantined_items}"
        )

    if spec.expected_any_flags:
        observed_flags = {fl for q in report.section_2_quarantined_items for fl in q.security_flags}
        assert any(req in observed_flags for req in spec.expected_any_flags), (
            f"[{spec.key}] none of {spec.expected_any_flags} found in {observed_flags}"
        )


def test_scenario_coverage_breadth(synthetic_fixtures: dict[str, Path]) -> None:
    """Confirm multiple persisted test images exist on disk for every scenario group."""
    assert len(synthetic_fixtures) >= 37
    counts_by_group: dict[str, int] = {}
    for spec in SCENARIO_CATALOG:
        counts_by_group[spec.scenario_group] = counts_by_group.get(spec.scenario_group, 0) + 1

    for group_name, count in counts_by_group.items():
        assert count >= 2, f"Scenario group {group_name} must have multiple test images (found {count})"


def test_cli_exit_codes_contract(project_root: Path, synthetic_fixtures: dict[str, Path]) -> None:
    """Verify POSIX exit codes: 0 normal, 2 corrupt/polyglot, 3 critical with --fail-on-findings."""
    cli = str(project_root / "scripts" / "pixel_guard_cli.py")

    p_clean = subprocess.run(
        [sys.executable, cli, str(synthetic_fixtures["clean_control"]), "--fail-on-findings"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_clean.returncode == 0

    p_default_crit = subprocess.run(
        [sys.executable, cli, str(synthetic_fixtures["v1_low_contrast"])],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_default_crit.returncode == 0

    p_strict_crit = subprocess.run(
        [sys.executable, cli, str(synthetic_fixtures["v1_low_contrast"]), "--fail-on-findings"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_strict_crit.returncode == 3

    p_corrupt = subprocess.run(
        [sys.executable, cli, str(synthetic_fixtures["corrupt_polyglot"])],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_corrupt.returncode == 2


def test_nfr_1080p_latency_and_memory_budget(synthetic_fixtures: dict[str, Path]) -> None:
    """NFR-01 (<2.5s on 1080p) and NFR-02 (<512MB peak Python heap)."""
    t0 = time.perf_counter()
    report = scan_image(synthetic_fixtures["bench_1080p_mixed"])
    elapsed_s = time.perf_counter() - t0

    tracemalloc.start()
    scan_image(synthetic_fixtures["bench_1080p_mixed"])
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_bytes / (1024 * 1024)
    assert report.scan_status == "CRITICAL INJECTION DETECTED"
    assert report.visible_count >= 1
    assert report.quarantined_count >= 1
    assert elapsed_s < 2.5, f"1080p scan exceeded 2.5s budget: {elapsed_s:.2f}s"
    assert peak_mb < 512.0, f"Peak memory exceeded 512MB budget: {peak_mb:.1f}MB"


def test_reports_standardize_relative_paths(synthetic_fixtures: dict[str, Path]) -> None:
    """Verify ScanReport emits relative project paths rather than absolute local machine paths."""
    report = scan_image(synthetic_fixtures["v3_micro_text"])
    assert report.image_path == "tests/images/v3_micro_text.png"
    assert not Path(report.image_path).is_absolute()


def test_multipage_tiff_evaluates_each_page_independently(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify normal pages in a multi-page TIFF go to Section 1 and only actual threats go to Section 2."""
    from PIL import Image, ImageDraw
    from tests.generate_test_images import load_scalable_font

    # 1. Mixed 3-page TIFF: Pages 1 and 2 are safe visible text; only Page 3 is quarantined
    mixed_rep = scan_image(synthetic_fixtures["v7b_multipage_tiff_hidden"])
    assert mixed_rep.visible_count == 2
    assert [v.frame_index for v in mixed_rep.section_1_visible_text] == [0, 1]
    assert mixed_rep.quarantined_count == 1
    assert mixed_rep.section_2_quarantined_items[0].frame_index == 2
    assert "INACTIVE_FRAME_OBFUSCATION" not in mixed_rep.section_2_quarantined_items[0].security_flags

    # 2. Clean 3-page TIFF document: all 3 pages go to Section 1 and Scan Status is PASSED
    fnt = load_scalable_font(24)
    pages = []
    for idx in range(3):
        pg = Image.new("RGB", (800, 260), color=(255, 255, 255))
        ImageDraw.Draw(pg).text((40, 100), f"Document Page {idx + 1} Routine Calibration Record", fill=(20, 20, 20), font=fnt)
        pages.append(pg)
    clean_tiff = tmp_path / "clean_3page_doc.tiff"
    pages[0].save(clean_tiff, format="TIFF", save_all=True, append_images=pages[1:])

    clean_rep = scan_image(clean_tiff)
    assert clean_rep.scan_status == "PASSED"
    assert clean_rep.visible_count == 3
    assert clean_rep.quarantined_count == 0
