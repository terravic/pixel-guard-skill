"""Typed data structures for the pixel-guard deterministic analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ValidatedAsset:
    """Metadata produced after structural and magic-byte verification."""

    path: str
    filename: str
    sha256: str
    detected_format: str
    width: int
    height: int
    channels: int
    frames_total: int


@dataclass(frozen=True)
class MetadataEntry:
    """Single non-pixel container metadata string harvested from an image file."""

    source: str
    content: str
    suspicious: bool = False


@dataclass
class PassImage:
    """Single deterministic computer-vision representation queued for local OCR."""

    pass_id: str
    display_label: str
    channel_group: str
    frame_index: int
    image: np.ndarray
    scale_factor: float = 1.0
    offset_x: int = 0
    offset_y: int = 0
    psm_modes: tuple[int, ...] = (6,)


@dataclass
class DetectedRegion:
    """Consolidated text phrase localized in native 1x image coordinates."""

    text: str
    bbox: tuple[int, int, int, int]  # (x, y, w, h) in 1x native image coordinates
    confidence: float
    origin_pass: str
    display_method: str
    frame_index: int
    pass_crop_gray: np.ndarray | None = field(default=None, repr=False)


@dataclass(frozen=True)
class VisibilityProfile:
    """Colorimetric and spatial human-visibility metrics for a detected region."""

    contrast_ratio: float
    delta_e: float
    mean_alpha: float
    font_height_px: int
    foreground_rgb: tuple[int, int, int]
    background_rgb: tuple[int, int, int]
    foreground_hex: str
    background_hex: str
    foreground_lab: tuple[float, float, float]
    background_lab: tuple[float, float, float]
    is_human_visible: bool
    anomaly_flags: tuple[str, ...]


@dataclass(frozen=True)
class ThreatAssessment:
    """Result of evaluating a string against deterministic prompt-injection heuristics."""

    severity: str  # CLEAN, MEDIUM, HIGH, CRITICAL
    security_flags: tuple[str, ...]
    decoded_payloads: tuple[str, ...]
    max_token_entropy: float


@dataclass(frozen=True)
class VisibleTextItem:
    """Verified human-visible and threat-clean text region placed in Section 1."""

    text: str
    bbox: tuple[int, int, int, int]
    frame_index: int
    origin_pass: str
    confidence: float
    contrast_ratio: float
    delta_e: float
    mean_alpha: float
    foreground_hex: str
    background_hex: str
    foreground_lab: tuple[float, float, float]
    background_lab: tuple[float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": list(self.bbox),
            "frame_index": self.frame_index,
            "origin_pass": self.origin_pass,
            "confidence": round(self.confidence, 4),
            "contrast_ratio": round(self.contrast_ratio, 2),
            "delta_e": round(self.delta_e, 2),
            "mean_alpha": round(self.mean_alpha, 3),
            "foreground_hex": self.foreground_hex,
            "background_hex": self.background_hex,
            "foreground_lab": [round(v, 2) for v in self.foreground_lab],
            "background_lab": [round(v, 2) for v in self.background_lab],
        }


@dataclass(frozen=True)
class QuarantinedItem:
    """Camouflaged, metadata-smuggled, or adversarial finding placed in Section 2."""

    item_id: int
    risk_level: str  # MEDIUM, HIGH, CRITICAL
    category_label: str
    text: str
    detection_method: str
    origin_pass: str
    frame_index: int
    security_flags: tuple[str, ...]
    decoded_payloads: tuple[str, ...] = ()
    bbox: tuple[int, int, int, int] | None = None
    font_height_px: int | None = None
    contrast_ratio: float | None = None
    delta_e: float | None = None
    mean_alpha: float | None = None
    shannon_entropy: float | None = None
    foreground_hex: str | None = None
    background_hex: str | None = None
    foreground_lab: tuple[float, float, float] | None = None
    background_lab: tuple[float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "risk_level": self.risk_level,
            "category_label": self.category_label,
            "text": self.text,
            "decoded_payloads": list(self.decoded_payloads),
            "detection_method": self.detection_method,
            "origin_pass": self.origin_pass,
            "frame_index": self.frame_index,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "font_height_px": self.font_height_px,
            "contrast_ratio": round(self.contrast_ratio, 2) if self.contrast_ratio is not None else None,
            "delta_e": round(self.delta_e, 2) if self.delta_e is not None else None,
            "mean_alpha": round(self.mean_alpha, 3) if self.mean_alpha is not None else None,
            "shannon_entropy": round(self.shannon_entropy, 3) if self.shannon_entropy is not None else None,
            "foreground_hex": self.foreground_hex,
            "background_hex": self.background_hex,
            "foreground_lab": [round(v, 2) for v in self.foreground_lab] if self.foreground_lab is not None else None,
            "background_lab": [round(v, 2) for v in self.background_lab] if self.background_lab is not None else None,
            "security_flags": list(self.security_flags),
        }


@dataclass(frozen=True)
class ScanReport:
    """Complete deterministic pre-flight scan report for an image asset."""

    skill_name: str
    version: str
    image_filename: str
    image_path: str
    sha256: str
    format: str
    width: int
    height: int
    channels: int
    frames_analyzed: int
    frames_total: int
    scan_status: str  # PASSED, WARNING, CRITICAL INJECTION DETECTED
    analyzed_channels: tuple[str, ...]
    total_regions_found: int
    visible_count: int
    quarantined_count: int
    elapsed_ms: float
    system_theme: str
    section_1_visible_text: tuple[VisibleTextItem, ...]
    section_2_quarantined_items: tuple[QuarantinedItem, ...]
    metadata_entries: tuple[MetadataEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "version": self.version,
            "image_filename": self.image_filename,
            "image_path": self.image_path,
            "sha256": self.sha256,
            "format": self.format,
            "dimensions": {
                "width": self.width,
                "height": self.height,
                "channels": self.channels,
            },
            "frames_analyzed": self.frames_analyzed,
            "frames_total": self.frames_total,
            "scan_status": self.scan_status,
            "analyzed_channels": list(self.analyzed_channels),
            "total_regions_found": self.total_regions_found,
            "visible_count": self.visible_count,
            "quarantined_count": self.quarantined_count,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "system_theme": self.system_theme,
            "section_1_visible_text": [item.to_dict() for item in self.section_1_visible_text],
            "section_2_quarantined_items": [item.to_dict() for item in self.section_2_quarantined_items],
            "metadata_entries": [
                {
                    "source": m.source,
                    "content": m.content,
                    "suspicious": m.suspicious,
                }
                for m in self.metadata_entries
            ],
        }
