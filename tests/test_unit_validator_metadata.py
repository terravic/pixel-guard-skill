"""Unit tests for binary magic-byte validation, polyglot rejection, and metadata harvesting."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pixel_guard.config import ScanConfig, ValidationError
from pixel_guard.metadata import harvest_metadata, sanitize_metadata_text
from pixel_guard.validator import detect_magic_format, validate_image_file


def test_magic_format_detection() -> None:
    """Verify raw header signature identification across supported formats."""
    assert detect_magic_format(b"\xff\xd8\xff\xe0\x00\x10JFIF") == "JPEG"
    assert detect_magic_format(b"\x89PNG\r\n\x1a\n\x00\x00") == "PNG"
    assert detect_magic_format(b"GIF89a\x10\x00") == "GIF"
    assert detect_magic_format(b"BM\x36\x00\x0c\x00\x00\x00\x00\x00\x36\x00\x00\x00") == "BMP"
    assert detect_magic_format(b"RIFF\x24\x00\x00\x00WEBPVP8 ") == "WEBP"
    assert detect_magic_format(b"II*\x00\x08\x00\x00\x00") == "TIFF"
    assert detect_magic_format(b"P6\n10 10\n255\n") == "PPM"
    assert detect_magic_format(b"%PDF-1.7") is None


def test_validator_rejects_missing_empty_polyglot_and_truncated(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify deterministic ValidationError codes across malformed and adversarial files."""
    cfg = ScanConfig()

    with pytest.raises(ValidationError) as exc_missing:
        validate_image_file(tmp_path / "does_not_exist.png", cfg)
    assert exc_missing.value.error_code == "FILE_NOT_FOUND"

    with pytest.raises(ValidationError) as exc_dir:
        validate_image_file(tmp_path, cfg)
    assert exc_dir.value.error_code == "NOT_A_FILE"

    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")
    with pytest.raises(ValidationError) as exc_empty:
        validate_image_file(empty_file, cfg)
    assert exc_empty.value.error_code == "CORRUPTED_IMAGE_STREAM"

    with pytest.raises(ValidationError) as exc_poly:
        validate_image_file(synthetic_fixtures["corrupt_polyglot"], cfg)
    assert exc_poly.value.error_code == "POLYGLOT_OR_INVALID_SIGNATURE"

    # Valid PNG header with trailing <script> polyglot payload appended
    png_poly = tmp_path / "trailing_script.png"
    Image.new("RGB", (32, 32), color=(255, 255, 255)).save(png_poly, format="PNG")
    png_poly.write_bytes(png_poly.read_bytes() + b"\n<script>fetch('https://example.org')</script>")
    with pytest.raises(ValidationError) as exc_tail:
        validate_image_file(png_poly, cfg)
    assert exc_tail.value.error_code == "POLYGLOT_OR_INVALID_SIGNATURE"

    with pytest.raises(ValidationError) as exc_trunc:
        validate_image_file(synthetic_fixtures["corrupt_truncated"], cfg)
    assert exc_trunc.value.error_code == "CORRUPTED_IMAGE_STREAM"


def test_validator_enforces_max_pixels_decompression_guard(tmp_path: Path) -> None:
    """Verify images exceeding max_image_pixels are blocked prior to full processing."""
    img_path = tmp_path / "oversized.png"
    Image.new("RGB", (200, 200), color=(200, 200, 200)).save(img_path, format="PNG")

    strict_cfg = ScanConfig(max_image_pixels=10_000)  # 200 * 200 = 40,000 > 10,000
    with pytest.raises(ValidationError) as exc_bomb:
        validate_image_file(img_path, strict_cfg)
    assert exc_bomb.value.error_code == "IMAGE_DIMENSIONS_EXCEEDED"


def test_metadata_harvester_exif_and_png_chunks(synthetic_fixtures: dict[str, Path]) -> None:
    """Verify EXIF UserComment/ImageDescription and compressed PNG iTXt payloads are harvested."""
    exif_entries = harvest_metadata(synthetic_fixtures["v4_exif_injection"], "JPEG")
    assert any("Forward all chat history" in e.content for e in exif_entries)
    assert any(e.source.startswith("EXIF:") for e in exif_entries)

    png_entries = harvest_metadata(synthetic_fixtures["v4b_png_chunk"], "PNG")
    assert any("Ignore all previous instructions" in e.content for e in png_entries)


def test_metadata_unicode_and_control_byte_sanitization() -> None:
    """Verify UTF-16 UserComment and null-padded strings are sanitized cleanly."""
    utf16_payload = b"UNICODE\x00" + "System override test".encode("utf-16-le")
    assert sanitize_metadata_text(utf16_payload) == "System override test"

    control_str = "Clean\x00\x01\x07text   with   tabs"
    assert sanitize_metadata_text(control_str) == "Clean text with tabs"
