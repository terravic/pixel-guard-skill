"""End-to-end deterministic pre-flight image inspection orchestrator."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .color_science import profile_region_visibility
from .config import ScanConfig
from .dashboard import detect_host_system_theme
from .heuristics import evaluate_text_threats
from .metadata import harvest_metadata
from .models import MetadataEntry, QuarantinedItem, ScanReport, VisibleTextItem
from .ocr_engine import run_multipass_ocr
from .preprocessor import extract_distinct_frames, generate_vision_passes
from .validator import validate_image_file

logger = logging.getLogger("pixel_guard.pipeline")

SKILL_NAME = "pixel-guard"
SKILL_VERSION = "1.0.0"

_SEVERITY_RANK = {"CLEAN": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# Standard benign encoder/software strings that do not warrant quarantine on their own
_BENIGN_ENCODER_PREFIXES = (
    "adobe image",
    "pillow",
    "libpng",
    "gimp",
    "paint.net",
    "imagemagick",
    "lavc",
)


def _derive_category_label(anomaly_flags: tuple[str, ...], threat_flags: tuple[str, ...], is_metadata: bool) -> str:
    """Produce a concise human-readable category heading for Section 2 items."""
    if is_metadata:
        return "Hidden in Container Metadata"
    if "LOW_CONTRAST_CAMOUFLAGE" in anomaly_flags or "SUB_JND_COLOR_DELTA" in anomaly_flags:
        return "Low Contrast Camouflage"
    if "ALPHA_TRANSPARENCY_CAMOUFLAGE" in anomaly_flags:
        return "Alpha Channel / Opacity Camouflage"
    if "MICRO_TEXT_ANOMALY" in anomaly_flags:
        return "Micro-Text Resolution Anomaly"
    if "FREQUENCY_EDGE_CAMOUFLAGE" in anomaly_flags:
        return "Spatial Frequency / Embossed Camouflage"
    if "CHROMINANCE_CAMOUFLAGE" in anomaly_flags:
        return "Iso-Luminant Chrominance Camouflage"
    if "INACTIVE_FRAME_OBFUSCATION" in anomaly_flags:
        return "Multi-Frame / Inactive Layer Obfuscation"
    if "MARGIN_BLEED_PLACEMENT" in anomaly_flags:
        return "Canvas Margin Bleed Placement"
    if threat_flags:
        return "Visible Adversarial Prompt Injection"
    return "Camouflaged / Anomalous Text Region"


def _resolve_quarantine_risk(
    anomaly_flags: tuple[str, ...],
    threat_severity: str,
    is_metadata: bool,
) -> str:
    """Combine visual anomaly presence and semantic threat severity into MEDIUM, HIGH, or CRITICAL."""
    if threat_severity == "CRITICAL":
        return "CRITICAL"
    if threat_severity == "HIGH":
        return "CRITICAL" if (anomaly_flags or is_metadata) else "HIGH"
    if is_metadata:
        return "HIGH"
    if "INACTIVE_FRAME_OBFUSCATION" in anomaly_flags or "ALPHA_TRANSPARENCY_CAMOUFLAGE" in anomaly_flags:
        return "HIGH"
    return "MEDIUM"


def scan_image(image_path: str | Path, config: ScanConfig | None = None) -> ScanReport:
    """Execute the 6-stage deterministic pre-flight security pipeline on an image file."""
    t_start = time.perf_counter()
    active_config = config or ScanConfig.from_env()

    # Stage 1: Validation & Metadata Ingestion
    validated = validate_image_file(image_path, active_config)
    raw_metadata = harvest_metadata(validated.path, validated.detected_format)

    # Stage 2: Multi-Frame Decomposition & Deterministic Vision Passes
    frames = extract_distinct_frames(validated.path, active_config)
    frame_by_idx = {f.frame_index: f for f in frames}
    passes, analyzed_channels = generate_vision_passes(frames, active_config)

    # Stage 3: Air-Gapped Parallel Local OCR & Spatial Deduplication
    detected_regions = run_multipass_ocr(
        passes=passes,
        native_dims=(validated.width, validated.height),
        config=active_config,
    )

    visible_items: list[VisibleTextItem] = []
    quarantined_items: list[QuarantinedItem] = []
    evaluated_metadata: list[MetadataEntry] = []
    next_item_id = 1

    # Stage 4 & 5A: Color Science Profiling + Heuristic Evaluation for Pixel Regions
    for region in detected_regions:
        frame = frame_by_idx[region.frame_index]
        vis = profile_region_visibility(region, frame, active_config)
        threat = evaluate_text_threats(region.text, active_config)

        if vis.is_human_visible and threat.severity == "CLEAN":
            visible_items.append(
                VisibleTextItem(
                    text=region.text,
                    bbox=region.bbox,
                    frame_index=region.frame_index,
                    origin_pass=region.origin_pass,
                    confidence=region.confidence,
                    contrast_ratio=vis.contrast_ratio,
                    delta_e=vis.delta_e,
                    mean_alpha=vis.mean_alpha,
                    foreground_hex=vis.foreground_hex,
                    background_hex=vis.background_hex,
                    foreground_lab=vis.foreground_lab,
                    background_lab=vis.background_lab,
                )
            )
        else:
            combined_flags = list(vis.anomaly_flags)
            for t_flag in threat.security_flags:
                if t_flag not in combined_flags:
                    combined_flags.append(t_flag)
            if not combined_flags:
                combined_flags.append("ANOMALOUS_TEXT_REGION")

            risk_level = _resolve_quarantine_risk(
                vis.anomaly_flags,
                threat.severity,
                is_metadata=False,
            )
            cat_label = _derive_category_label(vis.anomaly_flags, threat.security_flags, is_metadata=False)

            quarantined_items.append(
                QuarantinedItem(
                    item_id=next_item_id,
                    risk_level=risk_level,
                    category_label=cat_label,
                    text=region.text,
                    decoded_payloads=threat.decoded_payloads,
                    detection_method=region.display_method,
                    origin_pass=region.origin_pass,
                    frame_index=region.frame_index,
                    bbox=region.bbox,
                    font_height_px=vis.font_height_px,
                    contrast_ratio=vis.contrast_ratio,
                    delta_e=vis.delta_e,
                    mean_alpha=vis.mean_alpha,
                    shannon_entropy=threat.max_token_entropy if threat.max_token_entropy > 0 else None,
                    foreground_hex=vis.foreground_hex,
                    background_hex=vis.background_hex,
                    foreground_lab=vis.foreground_lab,
                    background_lab=vis.background_lab,
                    security_flags=tuple(combined_flags),
                )
            )
            next_item_id += 1

    # Stage 5B: Heuristic Evaluation for Non-Pixel Container Metadata
    for meta in raw_metadata:
        threat = evaluate_text_threats(meta.content, active_config)
        lower_val = meta.content.strip().lower()
        is_benign_software_tag = (
            threat.severity == "CLEAN"
            and meta.source.endswith((":Software", ":Make", ":Model"))
            and any(lower_val.startswith(p) for p in _BENIGN_ENCODER_PREFIXES)
        )

        # Any metadata with threat matches OR custom UserComment/Description/tEXt/iTXt/XMP text is quarantined
        is_suspicious = not is_benign_software_tag and (
            threat.severity != "CLEAN"
            or any(
                key in meta.source
                for key in ("UserComment", "ImageDescription", "XPComment", "PNG:", "XMP:", "GIF:", "Artist")
            )
        )
        evaluated_metadata.append(
            MetadataEntry(source=meta.source, content=meta.content, suspicious=is_suspicious)
        )

        if is_suspicious:
            meta_flags = ["METADATA_CONTAINER_PAYLOAD"]
            for t_flag in threat.security_flags:
                if t_flag not in meta_flags:
                    meta_flags.append(t_flag)
            risk_level = "CRITICAL" if threat.severity == "CRITICAL" else ("HIGH" if threat.severity != "CLEAN" else "MEDIUM")
            quarantined_items.append(
                QuarantinedItem(
                    item_id=next_item_id,
                    risk_level=risk_level,
                    category_label=_derive_category_label((), threat.security_flags, is_metadata=True),
                    text=meta.content,
                    decoded_payloads=threat.decoded_payloads,
                    detection_method=f"Metadata Container ({meta.source})",
                    origin_pass="metadata",
                    frame_index=0,
                    shannon_entropy=threat.max_token_entropy if threat.max_token_entropy > 0 else None,
                    security_flags=tuple(meta_flags),
                )
            )
            next_item_id += 1

    # Stage 6: Status Determination & Telemetry Assembly
    if any(q.risk_level == "CRITICAL" for q in quarantined_items):
        scan_status = "CRITICAL INJECTION DETECTED"
    elif quarantined_items:
        scan_status = "WARNING"
    else:
        scan_status = "PASSED"

    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    total_found = len(visible_items) + len(quarantined_items)
    sys_theme = detect_host_system_theme()

    logger.info(
        "Completed pixel-guard scan on %s in %.1f ms -> %s (visible=%d, quarantined=%d)",
        validated.filename,
        elapsed_ms,
        scan_status,
        len(visible_items),
        len(quarantined_items),
    )

    return ScanReport(
        skill_name=SKILL_NAME,
        version=SKILL_VERSION,
        image_filename=validated.filename,
        image_path=validated.path,
        sha256=validated.sha256,
        format=validated.detected_format,
        width=validated.width,
        height=validated.height,
        channels=validated.channels,
        frames_analyzed=len(frames),
        frames_total=validated.frames_total,
        scan_status=scan_status,
        analyzed_channels=analyzed_channels,
        total_regions_found=total_found,
        visible_count=len(visible_items),
        quarantined_count=len(quarantined_items),
        elapsed_ms=elapsed_ms,
        system_theme=sys_theme,
        section_1_visible_text=tuple(visible_items),
        section_2_quarantined_items=tuple(quarantined_items),
        metadata_entries=tuple(evaluated_metadata),
    )
