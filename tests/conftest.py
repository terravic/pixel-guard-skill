"""Shared pytest session fixtures for pixel-guard."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Prevent CLI tests from spawning persistent background daemons during automated test runs
os.environ.setdefault("PIXEL_GUARD_NO_AUTO_DAEMON", "1")

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from tests.generate_test_images import generate_all_test_images  # noqa: E402


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the resolved Path to the pixel-guard repository root."""
    return _ROOT


@pytest.fixture(scope="session")
def synthetic_fixtures(project_root: Path) -> dict[str, Path]:
    """Generate and return all 37 deterministic synthetic test images inside tests/images/."""
    images_dir = project_root / "tests" / "images"
    return generate_all_test_images(images_dir)
