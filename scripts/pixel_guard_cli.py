#!/usr/bin/env python3
"""Standalone CLI entry script for pixel-guard."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from pixel_guard.cli_entry import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
