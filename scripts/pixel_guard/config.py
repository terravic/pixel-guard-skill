"""Configuration and exception types for pixel-guard."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


class PixelGuardError(Exception):
    """Base exception for pixel-guard operational failures."""


class ValidationError(PixelGuardError):
    """Raised when an input file fails structural, signature, or safety validation."""

    def __init__(self, message: str, error_code: str = "VALIDATION_FAILED") -> None:
        super().__init__(message)
        self.error_code = error_code


class OCREngineUnavailableError(PixelGuardError):
    """Raised when no local OCR backend is available on the host system."""


def get_project_root() -> Path:
    """Resolve the skill root directory relative to this module."""
    return Path(__file__).resolve().parent.parent.parent


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValidationError(
            f"Invalid float environment variable {name}={raw!r}",
            error_code="INVALID_CONFIGURATION",
        ) from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError(
            f"Invalid integer environment variable {name}={raw!r}",
            error_code="INVALID_CONFIGURATION",
        ) from exc


@dataclass(frozen=True)
class ScanConfig:
    """Runtime thresholds and execution parameters for deterministic scanning."""

    wcag_contrast_threshold: float = 3.0
    ciede2000_delta_e_threshold: float = 15.0
    alpha_opacity_threshold: float = 0.30
    micro_text_height_px: int = 8
    entropy_threshold: float = 4.7
    entropy_min_length: int = 24
    max_image_pixels: int = 36_000_000
    max_frames: int = 8
    frame_diff_threshold: float = 1.0
    ocr_workers: int = 4
    ocr_min_confidence: float = 0.32
    tesseract_cmd: str | None = None
    ocr_backend: str = "auto"

    @classmethod
    def from_env(cls) -> ScanConfig:
        """Instantiate configuration populated from PIXEL_GUARD_* environment variables."""
        tess_cmd = os.getenv("PIXEL_GUARD_TESSERACT_CMD")
        return cls(
            wcag_contrast_threshold=_env_float("PIXEL_GUARD_WCAG_MIN", 3.0),
            ciede2000_delta_e_threshold=_env_float("PIXEL_GUARD_DELTA_E_MIN", 15.0),
            alpha_opacity_threshold=_env_float("PIXEL_GUARD_ALPHA_MIN", 0.30),
            micro_text_height_px=_env_int("PIXEL_GUARD_MIN_HEIGHT_PX", 8),
            entropy_threshold=_env_float("PIXEL_GUARD_ENTROPY_MAX", 4.7),
            entropy_min_length=_env_int("PIXEL_GUARD_ENTROPY_MIN_LEN", 24),
            max_image_pixels=_env_int("PIXEL_GUARD_MAX_PIXELS", 36_000_000),
            max_frames=_env_int("PIXEL_GUARD_MAX_FRAMES", 8),
            frame_diff_threshold=_env_float("PIXEL_GUARD_FRAME_DIFF_MIN", 1.0),
            ocr_workers=max(1, _env_int("PIXEL_GUARD_OCR_WORKERS", 4)),
            ocr_min_confidence=_env_float("PIXEL_GUARD_OCR_MIN_CONF", 0.32),
            tesseract_cmd=tess_cmd.strip() if tess_cmd and tess_cmd.strip() else None,
            ocr_backend=os.getenv("PIXEL_GUARD_OCR_BACKEND", "auto").strip().lower(),
        )

    def with_overrides(self, overrides: Mapping[str, Any] | None) -> ScanConfig:
        """Return a copy of this configuration with explicit dictionary overrides applied."""
        if not overrides:
            return self
        valid_fields = {f for f in self.__dataclass_fields__}
        filtered = {k: v for k, v in overrides.items() if k in valid_fields and v is not None}
        return replace(self, **filtered)

    @classmethod
    def from_json_file(cls, config_path: Path) -> ScanConfig:
        """Load configuration from a JSON file merged atop environment defaults."""
        if not config_path.is_file():
            raise ValidationError(
                f"Configuration file does not exist: {config_path}",
                error_code="MISSING_CONFIG_FILE",
            )
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(
                f"Failed to parse configuration JSON {config_path}: {exc}",
                error_code="INVALID_CONFIG_JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise ValidationError(
                "Configuration JSON root must be an object",
                error_code="INVALID_CONFIG_JSON",
            )
        return cls.from_env().with_overrides(payload)
