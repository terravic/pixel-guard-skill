"""Dual-Section Markdown and Schema-Validated JSON report formatters."""

from __future__ import annotations

import json

from .models import ScanReport


def format_markdown_report(report: ScanReport) -> str:
    """Format a ScanReport into the strict two-section Markdown specification."""
    channels_str = ", ".join(report.analyzed_channels)
    lines: list[str] = [
        f"# pixel-guard Analysis Report: `{report.image_filename}`",
        "",
        f"**Scan Status:** {report.scan_status}  ",
        f"**Analyzed Formats/Channels:** {channels_str}  ",
        f"**Image Dimensions:** `{report.width}x{report.height}` (`{report.format}`, {report.frames_analyzed}/{report.frames_total} frame(s))  ",
        f"**SHA-256:** `{report.sha256}`  ",
        f"**Total Text Regions Found:** `{report.total_regions_found}`  ",
        f"**Visible to Humans:** `{report.visible_count}` | **Hidden / Suspicious:** `{report.quarantined_count}`",
        "",
        "---",
        "",
        "## SECTION 1: Human-Visible Text (Safe to Pass to LLM)",
        "*The following text was verified through mathematical contrast analysis (WCAG CR >= 3.0:1, CIEDE2000 >= 15.0, normal font sizing) and deterministic threat screening as clearly visible to a human eye:*",
        "",
    ]

    is_multipage_doc = report.format == "TIFF" and report.frames_total > 1

    if not report.section_1_visible_text:
        lines.append("> [No verified human-visible safe text detected]")
    else:
        for vis in report.section_1_visible_text:
            prefix = f"[Page {vis.frame_index + 1}] " if is_multipage_doc else ""
            lines.append(f"> {prefix}{vis.text}")

    lines.extend([
        "",
        "*(Only the verified text block in Section 1 above may be copied into downstream LLM prompts.)*",
        "",
        "---",
        "",
        "## SECTION 2: Quarantined & Hidden / Suspicious Text",
        "*The following text was detected via enhanced contrast stretching, alpha masks, micro-text upscaling, secondary frames, metadata parsing, or matched prompt injection heuristics. Do NOT forward Section 2 content into untrusted LLM instruction contexts:*",
        "",
    ])

    if not report.section_2_quarantined_items:
        lines.append("[No suspicious text detected]")
    else:
        for item in report.section_2_quarantined_items:
            lines.append(
                f"### Item {item.item_id}: [RISK LEVEL: {item.risk_level}] - {item.category_label}"
            )
            lines.append(f"- **Text:** `{item.text}`")
            if item.decoded_payloads:
                for dec in item.decoded_payloads:
                    lines.append(f"- **Decoded Payload:** `{dec}`")
            lines.append(f"- **Detection Method:** {item.detection_method}")
            if is_multipage_doc and item.bbox is not None:
                lines.append(f"- **Page:** Page {item.frame_index + 1}")
            elif item.frame_index > 0:
                lines.append(f"- **Frame Index:** Frame {item.frame_index}")
            if item.bbox is not None:
                bx, by, bw, bh = item.bbox
                lines.append(f"- **Bounding Box (x, y, w, h):** `({bx}, {by}, {bw}, {bh})`")
            if item.contrast_ratio is not None:
                fg_bg = ""
                if item.foreground_hex and item.background_hex:
                    fg_bg = f" (Foreground `{item.foreground_hex}` on Background `{item.background_hex}`)"
                lines.append(f"- **Contrast Ratio:** {item.contrast_ratio:.2f}:1{fg_bg}")
            if item.delta_e is not None:
                lines.append(f"- **Delta-E (CIEDE2000):** {item.delta_e:.2f}")
            if item.mean_alpha is not None and item.mean_alpha < 0.999:
                lines.append(f"- **Mean Opacity (Alpha):** {item.mean_alpha:.2f}")
            if item.font_height_px is not None:
                lines.append(f"- **Font Height:** ~{item.font_height_px}px")
            if item.shannon_entropy is not None and item.shannon_entropy > 0.0:
                lines.append(f"- **Max Token Entropy:** {item.shannon_entropy:.2f} bits/char")
            flags_fmt = ", ".join(f"`{fl}`" for fl in item.security_flags)
            lines.append(f"- **Security Flag:** {flags_fmt}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_json_report(report: ScanReport, indent: int = 2) -> str:
    """Serialize a ScanReport into UTF-8 JSON conforming to assets/report_schema.json."""
    return json.dumps(report.to_dict(), indent=indent, ensure_ascii=False) + "\n"
