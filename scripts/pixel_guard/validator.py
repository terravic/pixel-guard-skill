"""Magic-byte signature verification, polyglot detection, and decompression guards."""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

from PIL import Image, ImageSequence, UnidentifiedImageError

from .config import ScanConfig, ValidationError, to_project_relative_path
from .models import ValidatedAsset

logger = logging.getLogger("pixel_guard.validator")
PIL_LIMIT_LOCK = threading.Lock()

# Binary header markers indicative of script/executable polyglots masquerading as images
_POLYGLOT_MARKERS: tuple[bytes, ...] = (
    b"<!doctype html",
    b"<html",
    b"<script",
    b"<?php",
    b"\x7felf",
)

_CHANNEL_MAP: dict[str, int] = {
    "1": 1,
    "L": 1,
    "P": 4,  # Palette images can carry transparency indices
    "RGB": 3,
    "RGBA": 4,
    "CMYK": 4,
    "YCbCr": 3,
    "LAB": 3,
    "HSV": 3,
    "I": 1,
    "F": 1,
    "LA": 2,
    "PA": 4,
    "RGBa": 4,
}


def detect_magic_format(header: bytes) -> str | None:
    """Identify true container format from raw leading magic bytes."""
    if len(header) < 4:
        return None
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if header.startswith(b"BM") and len(header) >= 14:
        return "BMP"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "WEBP"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF"
    if len(header) >= 3 and header[0:1] == b"P" and header[1:2] in (b"1", b"2", b"3", b"4", b"5", b"6") and header[2:3] in (b" ", b"\t", b"\r", b"\n"):
        return "PPM"
    return None


def _check_polyglot_bytes(head: bytes, tail: bytes, detected_format: str | None) -> None:
    """Reject files embedding executable headers or active HTML/script payloads."""
    if head.startswith(b"MZ") and detected_format != "BMP":
        raise ValidationError(
            "Rejected PE executable header masquerading as an image file.",
            error_code="POLYGLOT_OR_INVALID_SIGNATURE",
        )
    if head.lstrip().startswith(b"#!") and detected_format is None:
        raise ValidationError(
            "Rejected script shebang header masquerading as an image file.",
            error_code="POLYGLOT_OR_INVALID_SIGNATURE",
        )
    head_lower = head[:1024].lower()
    for marker in _POLYGLOT_MARKERS:
        if marker in head_lower:
            raise ValidationError(
                f"Rejected polyglot payload containing signature {marker.decode('latin-1', errors='replace')!r} in file header.",
                error_code="POLYGLOT_OR_INVALID_SIGNATURE",
            )
    tail_lower = tail.lower()
    for script_marker in (b"<script", b"<?php", b"<!doctype html", b"<html"):
        if script_marker in tail_lower:
            raise ValidationError(
                f"Rejected polyglot payload containing trailing script signature {script_marker.decode('latin-1')!r}.",
                error_code="POLYGLOT_OR_INVALID_SIGNATURE",
            )


def validate_image_file(image_path: str | Path, config: ScanConfig) -> ValidatedAsset:
    """Validate existence, size bounds, magic bytes, polyglot safety, dimensions, and stream integrity."""
    path = Path(image_path)
    display_path = to_project_relative_path(path)
    if not path.exists():
        raise ValidationError(
            f"Image file not found: {display_path}",
            error_code="FILE_NOT_FOUND",
        )
    if not path.is_file():
        raise ValidationError(
            f"Target path is not a regular file: {display_path}",
            error_code="NOT_A_FILE",
        )

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        raise ValidationError(
            f"Unable to stat file {display_path}: {exc}",
            error_code="IO_ERROR",
        ) from exc

    if file_size == 0:
        raise ValidationError(
            f"Image file is empty (0 bytes): {display_path}",
            error_code="CORRUPTED_IMAGE_STREAM",
        )
    if file_size > config.max_file_bytes:
        raise ValidationError(
            f"Image file size ({file_size} bytes) exceeds configured safety limit ({config.max_file_bytes} bytes).",
            error_code="FILE_SIZE_EXCEEDED",
        )

    hasher = hashlib.sha256()
    head = b""
    tail = b""
    try:
        with path.open("rb") as fh:
            first_chunk = fh.read(65536)
            head = first_chunk[:4096]
            hasher.update(first_chunk)
            prev_chunk = first_chunk
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
                prev_chunk = (prev_chunk[-4096:] + chunk)[-4096:]
            tail = prev_chunk[-4096:]
    except OSError as exc:
        raise ValidationError(
            f"Unable to read file {display_path}: {exc}",
            error_code="IO_ERROR",
        ) from exc

    detected_format = detect_magic_format(head)
    _check_polyglot_bytes(head, tail, detected_format)

    if detected_format is None:
        raise ValidationError(
            f"Unsupported or unrecognized binary image signature in {path.name}. "
            "Supported raster formats: JPEG, PNG, WEBP, BMP, GIF, TIFF, PBM/PGM/PPM.",
            error_code="UNSUPPORTED_IMAGE_FORMAT",
        )

    with PIL_LIMIT_LOCK:
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = config.max_image_pixels
        try:
            with Image.open(path) as img:
                width, height = img.size
                if width <= 0 or height <= 0:
                    raise ValidationError(
                        f"Invalid image dimensions ({width}x{height}) in {path.name}.",
                        error_code="CORRUPTED_IMAGE_STREAM",
                    )
                if width * height > config.max_image_pixels:
                    raise ValidationError(
                        f"Image pixel count ({width * height}) exceeds configured safety limit ({config.max_image_pixels}).",
                        error_code="IMAGE_DIMENSIONS_EXCEEDED",
                    )
                frames_total = int(getattr(img, "n_frames", 1) or 1)
                mode = img.mode
                channels = _CHANNEL_MAP.get(mode, len(img.getbands()))
                img.verify()

            # Re-open and decode first frame raster to detect mid-stream truncation,
            # and verify dimensions of all subsequent frames up to config.max_frames.
            with Image.open(path) as img_check:
                img_check.load()
                if frames_total > 1:
                    for frame_idx, frame in enumerate(ImageSequence.Iterator(img_check)):
                        if frame_idx >= config.max_frames:
                            break
                        fw, fh = frame.size
                        if fw <= 0 or fh <= 0:
                            raise ValidationError(
                                f"Invalid frame {frame_idx} dimensions ({fw}x{fh}) in {path.name}.",
                                error_code="CORRUPTED_IMAGE_STREAM",
                            )
                        if fw * fh > config.max_image_pixels:
                            raise ValidationError(
                                f"Frame {frame_idx} pixel count ({fw * fh}) exceeds configured safety limit ({config.max_image_pixels}).",
                                error_code="IMAGE_DIMENSIONS_EXCEEDED",
                            )
        except Image.DecompressionBombError as exc:
            raise ValidationError(
                f"Rejected potential decompression bomb in {path.name}: {exc}",
                error_code="IMAGE_DIMENSIONS_EXCEEDED",
            ) from exc
        except ValidationError:
            raise
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as exc:
            raise ValidationError(
                f"Corrupted or truncated image stream in {path.name}: {exc}",
                error_code="CORRUPTED_IMAGE_STREAM",
            ) from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit

    logger.debug(
        "Validated %s (%s, %dx%d, %d ch, %d frames)",
        path.name,
        detected_format,
        width,
        height,
        channels,
        frames_total,
    )
    return ValidatedAsset(
        path=str(path),
        filename=path.name,
        sha256=hasher.hexdigest(),
        detected_format=detected_format,
        width=width,
        height=height,
        channels=channels,
        frames_total=frames_total,
    )
