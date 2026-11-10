"""Non-pixel container metadata harvester (EXIF, PNG chunks, XMP, IPTC, GIF comments)."""

from __future__ import annotations

import logging
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from .models import MetadataEntry

logger = logging.getLogger("pixel_guard.metadata")

try:
    import piexif  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    piexif = None

_PRINTABLE_CLEAN_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")

# Benign standard encoder/camera tags whose numeric/enum values are ignored unless textual
_TEXTUAL_EXIF_TAGS: set[str] = {
    "ImageDescription",
    "Make",
    "Model",
    "Software",
    "Artist",
    "Copyright",
    "DocumentName",
    "PageName",
    "HostComputer",
    "UserComment",
    "MakerNote",
    "XPTitle",
    "XPComment",
    "XPAuthor",
    "XPKeywords",
    "XPSubject",
    "CameraOwnerName",
    "BodySerialNumber",
    "LensModel",
}

_XP_UTF16_TAGS: set[str] = {"XPTitle", "XPComment", "XPAuthor", "XPKeywords", "XPSubject"}


def sanitize_metadata_text(raw: Any, tag_name: str = "") -> str:
    """Convert raw metadata value (bytes, tuple, str) into clean printable text."""
    if raw is None:
        return ""

    if isinstance(raw, (tuple, list)):
        # EXIF XP* UTF-16LE tags are sometimes exposed as tuples of byte integers
        if all(isinstance(x, int) and 0 <= x <= 255 for x in raw):
            raw = bytes(raw)
        else:
            return ""

    if isinstance(raw, bytes):
        if not raw:
            return ""
        if tag_name in _XP_UTF16_TAGS:
            decoded = raw.decode("utf-16-le", errors="ignore")
        elif raw.startswith(b"ASCII\x00\x00\x00"):
            decoded = raw[8:].decode("utf-8", errors="replace")
        elif raw.startswith(b"UNICODE\x00"):
            payload = raw[8:]
            # Try UTF-16BE then UTF-16LE based on null-byte alignment
            if len(payload) >= 2 and payload[0] == 0 and payload[1] != 0:
                decoded = payload.decode("utf-16-be", errors="ignore")
            else:
                decoded = payload.decode("utf-16-le", errors="ignore")
        elif raw.startswith(b"JIS\x00\x00\x00\x00\x00"):
            decoded = raw[8:].decode("shift_jis", errors="ignore")
        else:
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError:
                decoded = raw.decode("latin-1", errors="ignore")
    elif isinstance(raw, str):
        decoded = raw
    else:
        return ""

    cleaned = _PRINTABLE_CLEAN_RE.sub(" ", decoded).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned


def _parse_png_text_chunks(path: Path) -> list[tuple[str, str]]:
    """Directly parse PNG tEXt, zTXt, and iTXt chunks from binary stream."""
    results: list[tuple[str, str]] = []
    try:
        data = path.read_bytes()
    except OSError:
        return results

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return results

    offset = 8
    total_len = len(data)
    while offset + 8 <= total_len:
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        if chunk_end + 4 > total_len:
            break
        chunk_data = data[chunk_start:chunk_end]
        offset = chunk_end + 4  # Skip 4-byte CRC

        if chunk_type == b"tEXt" and b"\x00" in chunk_data:
            key_bytes, val_bytes = chunk_data.split(b"\x00", 1)
            key = key_bytes.decode("latin-1", errors="replace").strip()
            val = sanitize_metadata_text(val_bytes)
            if val:
                results.append((f"PNG:tEXt:{key}", val))
        elif chunk_type == b"zTXt" and b"\x00" in chunk_data:
            key_bytes, rest = chunk_data.split(b"\x00", 1)
            key = key_bytes.decode("latin-1", errors="replace").strip()
            if len(rest) >= 2 and rest[0] == 0:
                try:
                    decompressed = zlib.decompress(rest[1:])
                    val = sanitize_metadata_text(decompressed)
                    if val:
                        results.append((f"PNG:zTXt:{key}", val))
                except zlib.error:
                    pass
        elif chunk_type == b"iTXt" and b"\x00" in chunk_data:
            try:
                key_bytes, rest = chunk_data.split(b"\x00", 1)
                key = key_bytes.decode("utf-8", errors="replace").strip()
                if len(rest) >= 2:
                    comp_flag = rest[0]
                    # Skip compression flag (1B) + compression method (1B), then language tag & translated keyword
                    after_flags = rest[2:]
                    parts = after_flags.split(b"\x00", 2)
                    if len(parts) == 3:
                        text_bytes = parts[2]
                        if comp_flag == 1:
                            text_bytes = zlib.decompress(text_bytes)
                        val = sanitize_metadata_text(text_bytes)
                        if val:
                            results.append((f"PNG:iTXt:{key}", val))
            except (zlib.error, ValueError):
                pass
        elif chunk_type == b"IEND":
            break
    return results


def _extract_safe_xmp_strings(xmp_xml: str) -> list[str]:
    """Safely extract text values from XMP XML while blocking entity expansion."""
    lowered = xmp_xml.lower()
    if "<!entity" in lowered or "<!doctype" in lowered:
        # Strip DOCTYPE headers rather than expanding entities; return stripped text fallback
        stripped = re.sub(r"<[^>]+>", " ", xmp_xml)
        clean = sanitize_metadata_text(stripped)
        return [clean] if clean else []

    extracted: list[str] = []
    try:
        root = ET.fromstring(xmp_xml)
        for elem in root.iter():
            if elem.text and elem.text.strip():
                clean = sanitize_metadata_text(elem.text)
                if clean and len(clean) >= 3:
                    extracted.append(clean)
            for attr_name, attr_val in elem.attrib.items():
                if attr_val.startswith(("http://", "https://")) and ("w3.org" in attr_val or "purl.org" in attr_val):
                    continue
                local_attr = attr_name.split("}")[-1]
                if local_attr in {"about", "parseType", "lang", "xmptk"}:
                    continue
                clean_attr = sanitize_metadata_text(attr_val)
                if clean_attr and len(clean_attr) >= 4:
                    extracted.append(f"{local_attr}={clean_attr}")
    except ET.ParseError:
        stripped = re.sub(r"<[^>]+>", " ", xmp_xml)
        clean = sanitize_metadata_text(stripped)
        if clean:
            extracted.append(clean)
    return extracted


def harvest_metadata(image_path: str | Path, detected_format: str) -> list[MetadataEntry]:
    """Harvest textual metadata across EXIF, PNG chunks, XMP, IPTC, and GIF comments."""
    path = Path(image_path)
    seen: set[tuple[str, str]] = set()
    entries: list[MetadataEntry] = []

    def _add(source: str, content: str) -> None:
        if not content or len(content) < 2:
            return
        dedup_key = (source, content)
        if dedup_key not in seen:
            seen.add(dedup_key)
            entries.append(MetadataEntry(source=source, content=content))

    # 1. Parse EXIF via piexif when available (JPEG / TIFF / WEBP)
    if piexif is not None and detected_format in {"JPEG", "TIFF", "WEBP"}:
        try:
            exif_dict = piexif.load(str(path))
            for ifd_name in ("0th", "Exif", "1st", "GPS", "Interop"):
                ifd_map = exif_dict.get(ifd_name) or {}
                tag_table = piexif.TAGS.get(ifd_name, {})
                for tag_id, raw_val in ifd_map.items():
                    tag_info = tag_table.get(tag_id, {})
                    tag_name = tag_info.get("name", f"Tag_{tag_id}")
                    if tag_name in _TEXTUAL_EXIF_TAGS or isinstance(raw_val, (bytes, str)):
                        text_val = sanitize_metadata_text(raw_val, tag_name=tag_name)
                        if text_val and not text_val.isdigit():
                            _add(f"EXIF:{tag_name}", text_val)
        except Exception as exc:  # noqa: BLE001
            logger.debug("piexif extraction skipped on %s: %s", path.name, exc)

    # 2. Parse Pillow getexif(), info dictionary, XMP, and GIF comments
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif:
                for tag_id, raw_val in exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, f"Tag_{tag_id}")
                    if isinstance(raw_val, (bytes, str, tuple)):
                        text_val = sanitize_metadata_text(raw_val, tag_name=str(tag_name))
                        if text_val and not text_val.isdigit():
                            if not any(e.content == text_val for e in entries):
                                _add(f"EXIF:{tag_name}", text_val)

                # Inspect Exif sub-IFD (0x8769) via Pillow as fallback
                try:
                    sub_exif = exif.get_ifd(0x8769)
                    for sub_id, raw_val in sub_exif.items():
                        tag_name = ExifTags.TAGS.get(sub_id, f"SubTag_{sub_id}")
                        if isinstance(raw_val, (bytes, str, tuple)):
                            text_val = sanitize_metadata_text(raw_val, tag_name=str(tag_name))
                            if text_val and not text_val.isdigit():
                                if not any(e.content == text_val for e in entries):
                                    _add(f"EXIF:{tag_name}", text_val)
                except Exception:  # noqa: BLE001
                    pass

            for info_key, info_val in (img.info or {}).items():
                if info_key in {"exif", "icc_profile", "dpi", "gamma", "jfif", "jfif_version", "jfif_unit", "jfif_density", "transparency", "loop", "duration", "background", "aspect"}:
                    continue
                if "xmp" in info_key.lower():
                    xmp_str = sanitize_metadata_text(info_val)
                    for xmp_piece in _extract_safe_xmp_strings(
                        info_val.decode("utf-8", errors="ignore") if isinstance(info_val, bytes) else str(info_val)
                    ):
                        _add("XMP:Packet", xmp_piece)
                    if not entries and xmp_str:
                        _add("XMP:Packet", xmp_str)
                elif isinstance(info_val, (str, bytes)):
                    clean_info = sanitize_metadata_text(info_val)
                    if clean_info:
                        prefix = "GIF" if detected_format == "GIF" else detected_format
                        _add(f"{prefix}:{info_key}", clean_info)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pillow metadata inspection warning on %s: %s", path.name, exc)

    # 3. Direct PNG chunk scan so multiple tEXt/zTXt/iTXt chunks with identical keys are preserved
    if detected_format == "PNG":
        for chunk_source, chunk_val in _parse_png_text_chunks(path):
            if not any(e.content == chunk_val for e in entries):
                _add(chunk_source, chunk_val)

    # 4. Scan raw JPEG APP1 XMP packet if present and missed by Pillow
    if detected_format == "JPEG":
        try:
            raw_bytes = path.read_bytes()
            start_tag = b"<x:xmpmeta"
            idx = raw_bytes.find(start_tag)
            if idx != -1:
                end_idx = raw_bytes.find(b"</x:xmpmeta>", idx)
                if end_idx != -1:
                    packet = raw_bytes[idx : end_idx + 12].decode("utf-8", errors="ignore")
                    for xmp_piece in _extract_safe_xmp_strings(packet):
                        if not any(e.content == xmp_piece for e in entries):
                            _add("XMP:Packet", xmp_piece)
        except OSError:
            pass

    return entries
