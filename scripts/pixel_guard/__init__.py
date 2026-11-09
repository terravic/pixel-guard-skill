"""pixel-guard: Deterministic pre-flight image sanitization and hidden instruction defense."""

from .config import OCREngineUnavailableError, PixelGuardError, ScanConfig, ValidationError
from .dashboard import render_dashboard_html, write_dashboard_file
from .formatter import format_json_report, format_markdown_report
from .models import QuarantinedItem, ScanReport, VisibleTextItem
from .pipeline import SKILL_NAME, SKILL_VERSION, scan_image

__all__ = [
    "OCREngineUnavailableError",
    "PixelGuardError",
    "QuarantinedItem",
    "SKILL_NAME",
    "SKILL_VERSION",
    "ScanConfig",
    "ScanReport",
    "ValidationError",
    "VisibleTextItem",
    "format_json_report",
    "format_markdown_report",
    "render_dashboard_html",
    "scan_image",
    "write_dashboard_file",
]
