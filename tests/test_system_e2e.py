"""End-to-end system tests covering all 37 multi-instance synthetic fixtures, CLI exit codes, SLAs, and compliance."""

from __future__ import annotations

import re
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
    tracemalloc.start()
    t0 = time.perf_counter()
    report = scan_image(synthetic_fixtures["bench_1080p_mixed"])
    elapsed_s = time.perf_counter() - t0
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_bytes / (1024 * 1024)
    assert report.scan_status == "CRITICAL INJECTION DETECTED"
    assert report.visible_count >= 1
    assert report.quarantined_count >= 1
    assert elapsed_s < 2.5, f"1080p scan exceeded 2.5s budget: {elapsed_s:.2f}s"
    assert peak_mb < 512.0, f"Peak memory exceeded 512MB budget: {peak_mb:.1f}MB"


def test_repository_documentation_and_security_compliance_audit(project_root: Path) -> None:
    """Enforce zero emojis/icons, zero internal links, zero AI boilerplate, and zero LLM SDKs."""
    emoji_or_dingbat_re = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0000FE0F"
        "]"
    )
    corp_host = "corp" + "." + "google" + "." + "com"
    internal_domain_re = re.compile(rf"(?i)(?:{re.escape(corp_host)}|\bgo/[a-z0-9_-]+)")
    ai_boilerplate_re = re.compile(r"(?i)\b(?:it is worth noting that|in conclusion,|let's delve into)\b")
    forbidden_llm_imports_re = re.compile(
        r"^\s*(?:import|from)\s+(?:openai|anthropic|google\.generativeai|vertexai|langchain)\b",
        re.MULTILINE,
    )

    text_extensions = {".md", ".py", ".json", ".txt", ".toml", ".html"}
    skip_dirs = {".venv", "__pycache__", ".pytest_cache", "pixel_guard.egg-info", "images"}

    for path in project_root.rglob("*"):
        if any(part in skip_dirs or part.startswith(".") for part in path.relative_to(project_root).parts):
            continue
        if not path.is_file() or path.suffix not in text_extensions:
            continue

        content = path.read_text(encoding="utf-8")
        rel = path.relative_to(project_root)

        assert not emoji_or_dingbat_re.search(content), f"Forbidden emoji/icon found in {rel}"
        assert not internal_domain_re.search(content), f"Forbidden internal URL/path found in {rel}"

        if path.name != "test_system_e2e.py":
            assert not ai_boilerplate_re.search(content), f"AI boilerplate phrase found in {rel}"
            if path.suffix == ".py":
                assert not forbidden_llm_imports_re.search(content), f"Forbidden LLM SDK import in {rel}"
