#!/usr/bin/env python3
"""PreToolUse lifecycle hook gating direct multimodal reads of unscreened images."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from pixel_guard import (  # noqa: E402
    PixelGuardError,
    ScanConfig,
    format_markdown_report,
    scan_image,
)

_IMAGE_EXTENSIONS: set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".pbm",
    ".pgm",
    ".ppm",
}

_GATED_TOOLS: set[str] = {"view_file", "read_file", "read", "open_file"}


def _extract_target_path(tool_args: dict[str, Any]) -> str | None:
    """Extract target file path across common agent harness tool argument schemas."""
    for key in ("AbsolutePath", "file_path", "path", "TargetFile", "filepath"):
        val = tool_args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def evaluate_hook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a PreToolUse event payload and return a structured hook decision."""
    tool_call = payload.get("toolCall") or payload.get("tool_call") or {}
    tool_name = str(tool_call.get("name") or payload.get("tool_name") or "").strip().lower()
    tool_args = tool_call.get("args") or tool_call.get("arguments") or payload.get("tool_input") or {}

    if tool_name not in _GATED_TOOLS or not isinstance(tool_args, dict):
        return {"decision": "allow"}

    target_path = _extract_target_path(tool_args)
    if not target_path:
        return {"decision": "allow"}

    suffix = Path(target_path).suffix.lower()
    if suffix not in _IMAGE_EXTENSIONS:
        return {"decision": "allow"}

    hook_mode = os.getenv("PIXEL_GUARD_HOOK_MODE", "gate_threats").strip().lower()

    try:
        cfg = ScanConfig.from_env()
        report = scan_image(target_path, config=cfg)
        md_report = format_markdown_report(report)
    except PixelGuardError as exc:
        return {
            "decision": "deny",
            "reason": (
                f"pixel-guard blocked direct image ingestion because validation failed: {exc}"
            ),
        }

    if report.scan_status in {"CRITICAL INJECTION DETECTED", "WARNING"}:
        return {
            "decision": "deny",
            "reason": (
                f"pixel-guard blocked direct multimodal image read ({report.scan_status}). "
                "Use ONLY the verified Section 1 text from the pre-flight report below:\n\n"
                f"{md_report}"
            ),
        }

    if hook_mode == "strict_airgap":
        return {
            "decision": "deny",
            "reason": (
                "pixel-guard strict_airgap policy prevents raw image bytes from entering "
                "multimodal context. Verified Section 1 report:\n\n"
                f"{md_report}"
            ),
        }

    return {"decision": "allow"}


def main() -> int:
    """Read PreToolUse JSON from stdin and write decision JSON to stdout."""
    raw = sys.stdin.read().strip()
    if not raw:
        sys.stdout.write(json.dumps({"decision": "allow"}) + "\n")
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.stdout.write(json.dumps({"decision": "allow"}) + "\n")
        return 0

    if not isinstance(payload, dict):
        sys.stdout.write(json.dumps({"decision": "allow"}) + "\n")
        return 0

    result = evaluate_hook_payload(payload)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
