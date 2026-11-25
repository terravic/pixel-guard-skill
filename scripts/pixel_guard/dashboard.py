"""Standalone interactive HTML5 dashboard generator and local loopback Studio/SSE server."""

from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import hmac
import http.server
import io
import json
import logging
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import jsonschema
import numpy as np
from PIL import Image, ImageSequence

from .config import (
    OCREngineUnavailableError,
    PixelGuardError,
    ScanConfig,
    ValidationError,
    get_project_root,
    to_project_relative_path,
)
from .dashboard_ui import DASHBOARD_HTML_TEMPLATE
from .models import ScanReport
from .preprocessor import _amplify_deviation_to_ocr_surface, _morphological_deviation, composite_rgba_on_white
from .validator import PIL_LIMIT_LOCK

logger = logging.getLogger("pixel_guard.dashboard")

DEFAULT_STUDIO_PORT = 18765
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB ceiling
_MAX_PREVIEW_DIM = 1280
_MAX_PREVIEW_PAGES = 24
_MAX_SSE_CLIENTS = 16
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
_DATA_URI_PNG_RE = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/=]+$")
_SCRIPT_TAG_RE = re.compile(
    r"(<script id=\"pixel-guard-app-script\">)(.*?)(</script>)",
    re.DOTALL,
)
_SUPPORTED_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".pbm",
    ".pgm",
    ".ppm",
}

_SCAN_PATH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["image_path"],
    "additionalProperties": False,
    "properties": {
        "image_path": {"type": "string", "minLength": 1, "maxLength": 4096},
    },
}

_PUBLISH_WRAPPER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["report"],
    "additionalProperties": False,
    "properties": {
        "report": {"type": "object"},
        "dashboard_path": {"type": ["string", "null"], "maxLength": 4096},
    },
}

_PREVIEW_IMAGES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "original_data_uri": {"type": "string"},
        "reveal_data_uri": {"type": "string"},
        "reveal_frame_index": {"type": "integer", "minimum": 0},
        "frame_count": {"type": "integer", "minimum": 1, "maximum": _MAX_PREVIEW_PAGES},
        "frames": {
            "type": "array",
            "maxItems": _MAX_PREVIEW_PAGES,
            "items": {
                "type": "object",
                "required": ["frame_index", "width", "height", "original_data_uri", "reveal_data_uri"],
                "additionalProperties": False,
                "properties": {
                    "frame_index": {"type": "integer", "minimum": 0},
                    "width": {"type": "integer", "minimum": 1},
                    "height": {"type": "integer", "minimum": 1},
                    "original_data_uri": {"type": "string"},
                    "reveal_data_uri": {"type": "string"},
                },
            },
        },
    },
}

_REPORT_SCHEMA_CACHE: dict[str, Any] | None = None


def _get_report_schema() -> dict[str, Any]:
    """Load and cache assets/report_schema.json for strict payload validation."""
    global _REPORT_SCHEMA_CACHE
    if _REPORT_SCHEMA_CACHE is None:
        schema_path = get_project_root() / "assets" / "report_schema.json"
        _REPORT_SCHEMA_CACHE = json.loads(schema_path.read_text(encoding="utf-8"))
    return _REPORT_SCHEMA_CACHE


def _validate_loopback_url(url: str) -> str:
    """Validate that a Studio URL targets strictly loopback HTTP; fallback to default if invalid."""
    fallback = f"http://127.0.0.1:{DEFAULT_STUDIO_PORT}"
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return fallback
    if parsed.scheme != "http" or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return fallback
    port = parsed.port or DEFAULT_STUDIO_PORT
    host = parsed.hostname or "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def _studio_runtime_dir() -> Path:
    """Return a per-user 0700 temporary directory for loopback studio session tokens."""
    uid_tag = str(os.getuid()) if hasattr(os, "getuid") else "user"
    runtime_dir = Path(tempfile.gettempdir()) / f"pixel-guard-studio-{uid_tag}"
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(runtime_dir, 0o700)
    except OSError:
        pass
    return runtime_dir


def _token_file_for_port(port: int) -> Path:
    return _studio_runtime_dir() / f"port_{port}.token"


def _write_studio_token(port: int, token: str) -> None:
    """Atomically persist the loopback studio token with owner-only 0600 permissions."""
    if not token:
        return
    token_path = _token_file_for_port(port)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(token_path), flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        os.chmod(token_path, 0o600)
    except OSError as exc:
        logger.debug("Could not persist studio token file: %s", exc)


def read_studio_token(port: int) -> str:
    """Read the owner-only loopback studio token for a running Studio port if present."""
    token_path = _token_file_for_port(port)
    try:
        if token_path.is_file() and not token_path.is_symlink():
            return token_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def _clear_studio_token(port: int, expected_token: str) -> None:
    """Remove the runtime token file if it belongs to this server instance."""
    token_path = _token_file_for_port(port)
    try:
        if token_path.is_file() and not token_path.is_symlink():
            current = token_path.read_text(encoding="utf-8").strip()
            if hmac.compare_digest(current, expected_token):
                token_path.unlink(missing_ok=True)
    except OSError:
        pass


def _resolve_contained_path(raw_path: str, root: Path | None = None) -> Path:
    """Resolve a path and enforce strict containment within the repository workspace root."""
    base = (root or get_project_root()).resolve()
    cleaned = raw_path.strip()
    if "\x00" in cleaned:
        raise ValidationError(
            "Requested path contains illegal null byte.",
            error_code="PATH_OUTSIDE_WORKSPACE",
        )
    candidate = Path(cleaned)
    resolved = (base / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValidationError(
            "Requested path must reside within the repository workspace.",
            error_code="PATH_OUTSIDE_WORKSPACE",
        )
    return resolved


def _sanitize_upload_filename(raw_header_name: str) -> str:
    """Sanitize uploaded X-Filename header against traversal, null bytes, and control characters."""
    cleaned = raw_header_name.replace("\x00", "").replace("\\", "/")
    base = Path(cleaned).name
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    if not safe or safe in {".", ".."}:
        safe = "uploaded_image.png"
    if len(safe) > 128:
        stem = Path(safe).stem[:110] or "uploaded_image"
        suffix = Path(safe).suffix.lower()
        safe = f"{stem}{suffix}"
    if Path(safe).suffix.lower() not in _SUPPORTED_EXTS:
        safe = f"{safe}.png"
    return safe


def _validate_report_payload(report_data: Any) -> dict[str, Any]:
    """Validate an incoming ScanReport dictionary against report_schema.json and preview rules."""
    if not isinstance(report_data, dict):
        raise ValidationError("Report payload must be a JSON object.", error_code="INVALID_REPORT_SCHEMA")

    preview_images = report_data.get("preview_images")
    core_report = {k: v for k, v in report_data.items() if k != "preview_images"}

    try:
        jsonschema.validate(instance=core_report, schema=_get_report_schema())
    except jsonschema.ValidationError as exc:
        raise ValidationError(
            f"Report payload failed schema validation: {exc.message}",
            error_code="INVALID_REPORT_SCHEMA",
        ) from exc

    if preview_images is not None:
        try:
            jsonschema.validate(instance=preview_images, schema=_PREVIEW_IMAGES_SCHEMA)
        except jsonschema.ValidationError as exc:
            raise ValidationError(
                f"preview_images failed schema validation: {exc.message}",
                error_code="INVALID_REPORT_SCHEMA",
            ) from exc

        for uri_key in ("original_data_uri", "reveal_data_uri"):
            uri_val = preview_images.get(uri_key)
            if uri_val and not _DATA_URI_PNG_RE.match(uri_val):
                raise ValidationError(
                    f"preview_images.{uri_key} must be a valid base64 PNG data URI.",
                    error_code="INVALID_REPORT_SCHEMA",
                )
        for frame in preview_images.get("frames") or []:
            for uri_key in ("original_data_uri", "reveal_data_uri"):
                uri_val = frame.get(uri_key, "")
                if uri_val and not _DATA_URI_PNG_RE.match(uri_val):
                    raise ValidationError(
                        f"preview_images.frames[].{uri_key} must be a valid base64 PNG data URI.",
                        error_code="INVALID_REPORT_SCHEMA",
                    )

    return dict(report_data)


def _sanitize_error_message(message: str) -> str:
    """Ensure error messages returned over HTTP never disclose absolute local host paths."""
    root_str = str(get_project_root().resolve())
    sanitized = message.replace(root_str + os.sep, "").replace(root_str, ".")
    sanitized = re.sub(r"(/Users/|/home/|/usr/local/|/tmp/|/var/|[A-Za-z]:\\)[^\s'\",;:]+", "<local-path>", sanitized)
    return sanitized


def default_dashboard_path() -> Path:
    """Return the canonical dashboard.html path at the skill root directory."""
    return get_project_root() / "dashboard.html"


def detect_host_system_theme() -> str:
    """Query host environment appearance preference ('light' or 'dark') as fallback."""
    explicit = os.getenv("PIXEL_GUARD_SYSTEM_THEME", "").strip().lower()
    if explicit in {"light", "dark"}:
        return explicit

    gtk_theme = os.getenv("GTK_THEME", "").lower()
    if "dark" in gtk_theme:
        return "dark"
    if gtk_theme:
        return "light"

    if platform.system().lower() == "linux":
        try:
            proc = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True,
                text=True,
                check=False,
                timeout=1.0,
            )
            if proc.returncode == 0 and "dark" in proc.stdout.lower():
                return "dark"
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            pass

    return "light"


def _pil_to_png_data_uri(pil_img: Image.Image) -> str:
    """Resize if oversized (preserving aspect ratio) and encode as PNG data URI."""
    w, h = pil_img.size
    if max(w, h) > _MAX_PREVIEW_DIM:
        scale = _MAX_PREVIEW_DIM / float(max(w, h))
        new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        pil_img = pil_img.resize(new_size, resample=Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", compress_level=1)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _resolve_candidate_image(image_path: str | Path | None) -> Path | None:
    """Resolve relative or absolute image path against cwd and project root."""
    if not image_path:
        return None
    raw = str(image_path).strip()
    if not raw or raw.startswith("["):
        return None
    p = Path(raw)
    if p.is_file():
        return p
    if not p.is_absolute():
        from_root = get_project_root() / p
        if from_root.is_file():
            return from_root
        from_cwd = Path.cwd() / p
        if from_cwd.is_file():
            return from_cwd
    return None


def _render_frame_preview_pair(pil_frame: Image.Image, frame_index: int) -> dict[str, Any]:
    """Render Original and Enhanced Reveal base64 PNG data URIs for a single page or frame."""
    native_fw, native_fh = pil_frame.size
    has_alpha = pil_frame.mode in {"RGBA", "LA", "PA"} or (
        pil_frame.mode == "P" and "transparency" in pil_frame.info
    )
    rgba_full = np.array(
        pil_frame if pil_frame.mode == "RGBA" else pil_frame.convert("RGBA"),
        dtype=np.uint8,
    )
    if max(native_fw, native_fh) > _MAX_PREVIEW_DIM:
        scale = _MAX_PREVIEW_DIM / float(max(native_fw, native_fh))
        pw = max(1, int(round(native_fw * scale)))
        ph = max(1, int(round(native_fh * scale)))
        rgba = cv2.resize(rgba_full, (pw, ph), interpolation=cv2.INTER_AREA)
    else:
        rgba = rgba_full

    orig_uri = _pil_to_png_data_uri(Image.fromarray(rgba, mode="RGBA"))

    comp_rgb = composite_rgba_on_white(rgba)
    gray = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2GRAY)

    layers: list[np.ndarray] = [_morphological_deviation(gray, kernel_size=35)]

    lab = cv2.cvtColor(comp_rgb, cv2.COLOR_RGB2LAB)
    layers.append(_morphological_deviation(lab[:, :, 1], kernel_size=35))
    layers.append(_morphological_deviation(lab[:, :, 2], kernel_size=35))

    if has_alpha:
        alpha = rgba[:, :, 3]
        if int(alpha.max()) - int(alpha.min()) >= 2:
            layers.append(_morphological_deviation(alpha, kernel_size=35))
        low_alpha = alpha < 77
        if bool(np.any(low_alpha)):
            raw_gray = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
            vals = raw_gray[low_alpha]
            if vals.size > 16 and (int(vals.max()) - int(vals.min())) >= 2:
                bg_fill = int(np.median(vals))
                iso_raw = np.where(low_alpha, raw_gray, bg_fill).astype(np.uint8)
                layers.append(_morphological_deviation(iso_raw, kernel_size=35))

    combined_dev = np.maximum.reduce(layers)
    reveal_gray = _amplify_deviation_to_ocr_surface(combined_dev, noise_floor=2.5, min_cut=1.0)
    reveal_uri = _pil_to_png_data_uri(Image.fromarray(reveal_gray, mode="L"))

    return {
        "frame_index": frame_index,
        "width": int(native_fw),
        "height": int(native_fh),
        "original_data_uri": orig_uri,
        "reveal_data_uri": reveal_uri,
    }


def build_image_previews(
    image_path: str | Path | None,
    report_dict: dict[str, Any],
    max_image_pixels: int = 36_000_000,
) -> dict[str, Any]:
    """Generate per-page Original and Enhanced Reveal PNG data URIs for the dashboard."""
    path = _resolve_candidate_image(image_path)
    if path is None:
        return {}

    try:
        reveal_frame_idx = 0
        for q in report_dict.get("section_2_quarantined_items") or []:
            f_idx = int(q.get("frame_index") or 0)
            if f_idx > 0:
                reveal_frame_idx = f_idx
                break

        raw_frames: list[Image.Image] = []
        with PIL_LIMIT_LOCK:
            previous_limit = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = max_image_pixels
            try:
                with Image.open(path) as img:
                    for _, frame in zip(range(_MAX_PREVIEW_PAGES), ImageSequence.Iterator(img)):
                        fw, fh = frame.size
                        if fw <= 0 or fh <= 0 or (fw * fh) > max_image_pixels:
                            logger.warning("Skipping oversized preview frame (%dx%d) in %s", fw, fh, path.name)
                            break
                        raw_frames.append(frame.copy())
            finally:
                Image.MAX_IMAGE_PIXELS = previous_limit

        if not raw_frames:
            return {}

        frame_previews = [
            _render_frame_preview_pair(frame_img, idx)
            for idx, frame_img in enumerate(raw_frames)
        ]
        safe_rev_idx = min(reveal_frame_idx, len(frame_previews) - 1)

        return {
            "original_data_uri": frame_previews[0]["original_data_uri"],
            "reveal_data_uri": frame_previews[safe_rev_idx]["reveal_data_uri"],
            "reveal_frame_index": safe_rev_idx,
            "frame_count": len(frame_previews),
            "frames": frame_previews,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not generate image preview bundle for %s: %s", path.name, exc)
        return {}


def attach_dashboard_previews(
    report: ScanReport | dict[str, Any],
    source_image_path: str | Path | None = None,
    max_image_pixels: int = 36_000_000,
) -> dict[str, Any]:
    """Return a copy of the report dictionary enriched with preview_images if missing."""
    data = report.to_dict() if isinstance(report, ScanReport) else dict(report)
    if data.get("image_path"):
        data["image_path"] = to_project_relative_path(str(data["image_path"]))
    if not data.get("preview_images"):
        candidate = source_image_path or data.get("image_path")
        previews = build_image_previews(candidate, data, max_image_pixels=max_image_pixels)
        if previews:
            data["preview_images"] = previews
    return data


def _discover_available_images() -> list[dict[str, Any]]:
    """Return sorted list of test images in tests/images/ and workspace raster files using relative paths."""
    root = get_project_root()
    candidates: list[Path] = []
    images_dir = root / "tests" / "images"
    if images_dir.is_dir():
        candidates.extend(sorted(images_dir.iterdir()))

    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_file() and child.suffix.lower() in _SUPPORTED_EXTS:
                candidates.append(child)

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for path in candidates:
        if not path.is_file() or path.suffix.lower() not in _SUPPORTED_EXTS:
            continue
        resolved_key = str(path.resolve())
        if resolved_key in seen:
            continue
        seen.add(resolved_key)
        rel_path = to_project_relative_path(path)
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        items.append(
            {
                "name": path.name,
                "display": rel_path,
                "path": rel_path,
                "size_bytes": size_bytes,
            }
        )
    return items


def _browse_directory(raw_dir: str | None) -> dict[str, Any]:
    """List subdirectories and raster images inside raw_dir strictly within project root."""
    root = get_project_root().resolve()
    default_dir = (root / "tests" / "images").resolve()
    if not default_dir.is_dir():
        default_dir = root

    if raw_dir and raw_dir.strip():
        target = _resolve_contained_path(raw_dir, root=root)
        if not target.is_dir():
            target = default_dir
    else:
        target = default_dir

    dirs: list[dict[str, str]] = []
    images: list[dict[str, Any]] = []
    try:
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            rel_entry = to_project_relative_path(entry)
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": rel_entry})
            elif entry.is_file() and entry.suffix.lower() in _SUPPORTED_EXTS:
                try:
                    sz = entry.stat().st_size
                except OSError:
                    sz = 0
                images.append(
                    {
                        "name": entry.name,
                        "display": rel_entry,
                        "path": rel_entry,
                        "size_bytes": sz,
                    }
                )
    except OSError:
        pass

    parent_rel: str | None = None
    if target != root and target.parent != target:
        try:
            target.parent.resolve().relative_to(root)
            parent_rel = to_project_relative_path(target.parent) or "."
        except ValueError:
            parent_rel = None

    cur_rel = to_project_relative_path(target) or "."
    return {
        "current_dir": cur_rel,
        "parent_dir": parent_rel,
        "directories": dirs,
        "images": images,
    }


def render_dashboard_html_with_csp(
    report: ScanReport | dict[str, Any],
    studio_api_url: str = f"http://127.0.0.1:{DEFAULT_STUDIO_PORT}",
    source_image_path: str | Path | None = None,
    studio_token: str | None = None,
) -> tuple[str, str]:
    """Render self-contained dashboard.html alongside its exact SHA-256 Content-Security-Policy header."""
    safe_url = _validate_loopback_url(studio_api_url)
    effective_token = studio_token
    if effective_token is None:
        parsed = urllib.parse.urlparse(safe_url)
        effective_token = read_studio_token(parsed.port or DEFAULT_STUDIO_PORT)

    enriched = attach_dashboard_previews(report, source_image_path=source_image_path)
    payload_json = json.dumps(enriched, ensure_ascii=False).replace("</", "<\\/")
    url_json = json.dumps(safe_url, ensure_ascii=False).replace("</", "<\\/")
    token_json = json.dumps(effective_token or "", ensure_ascii=False).replace("</", "<\\/")

    rendered = DASHBOARD_HTML_TEMPLATE.replace("__PIXEL_GUARD_JSON_PAYLOAD__", payload_json)
    rendered = rendered.replace("__PIXEL_GUARD_STUDIO_URL__", url_json)
    rendered = rendered.replace("__PIXEL_GUARD_STUDIO_TOKEN__", token_json)

    match = _SCRIPT_TAG_RE.search(rendered)
    if match:
        script_hash = base64.b64encode(
            hashlib.sha256(match.group(2).encode("utf-8")).digest()
        ).decode("ascii")
        script_src = f"'sha256-{script_hash}'"
    else:
        script_src = "'none'"

    csp_meta = (
        f"default-src 'none'; script-src {script_src}; style-src 'unsafe-inline'; "
        "img-src data:; font-src 'self' data:; "
        "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
        "object-src 'none'; base-uri 'none'; form-action 'none'"
    )
    rendered = rendered.replace("__PIXEL_GUARD_CSP_META__", csp_meta)
    csp_header = f"{csp_meta}; frame-ancestors 'none'"
    return rendered, csp_header


def render_dashboard_html(
    report: ScanReport | dict[str, Any],
    studio_api_url: str = f"http://127.0.0.1:{DEFAULT_STUDIO_PORT}",
    source_image_path: str | Path | None = None,
    studio_token: str | None = None,
) -> str:
    """Render self-contained dashboard.html populated with empirical ScanReport data and previews."""
    html, _ = render_dashboard_html_with_csp(
        report,
        studio_api_url=studio_api_url,
        source_image_path=source_image_path,
        studio_token=studio_token,
    )
    return html


def write_dashboard_file(
    report: ScanReport | dict[str, Any],
    output_path: str | Path | None = None,
    studio_api_url: str = f"http://127.0.0.1:{DEFAULT_STUDIO_PORT}",
    source_image_path: str | Path | None = None,
    studio_token: str | None = None,
) -> Path:
    """Write standalone dashboard.html (defaulting to root dashboard.html) and return its Path."""
    out = Path(output_path) if output_path is not None else default_dashboard_path()
    html = render_dashboard_html(
        report,
        studio_api_url=studio_api_url,
        source_image_path=source_image_path,
        studio_token=studio_token,
    )
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise PixelGuardError(f"Unable to write dashboard file {to_project_relative_path(out)}: {exc}") from exc
    return out.resolve()


class DashboardSSEServer:
    """Loopback HTTP + SSE Studio Server supporting Load Image dialog, directory browsing, and uploads."""

    def __init__(
        self,
        initial_report: ScanReport | dict[str, Any],
        host: str = "127.0.0.1",
        port: int = DEFAULT_STUDIO_PORT,
        dashboard_file_path: Path | None = None,
        config: ScanConfig | None = None,
        idle_timeout_seconds: float | None = None,
        studio_token: str | None = None,
    ) -> None:
        self._config = config or ScanConfig.from_env()
        self._report_dict: dict[str, Any] = attach_dashboard_previews(
            initial_report,
            max_image_pixels=self._config.max_image_pixels,
        )
        self._lock = threading.Lock()
        self._sse_lock = threading.Lock()
        self._active_sse_clients = 0
        self._version = 1
        self._last_activity = time.monotonic()
        self._dashboard_file_path = (
            dashboard_file_path.resolve() if dashboard_file_path else default_dashboard_path()
        )
        self._idle_timeout = idle_timeout_seconds
        self.host = host
        self.studio_token = (
            studio_token
            or os.getenv("PIXEL_GUARD_STUDIO_TOKEN", "").strip()
            or secrets.token_urlsafe(32)
        )
        self._httpd = http.server.ThreadingHTTPServer((host, port), self._make_handler())
        self.port = int(self._httpd.server_address[1])
        self.api_url = f"http://{self.host}:{self.port}"
        _write_studio_token(self.port, self.studio_token)

        if self._idle_timeout is not None and self._idle_timeout > 0:
            watchdog = threading.Thread(target=self._idle_watchdog, daemon=True)
            watchdog.start()

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def _idle_watchdog(self) -> None:
        assert self._idle_timeout is not None
        while True:
            time.sleep(5.0)
            if (time.monotonic() - self._last_activity) > self._idle_timeout:
                logger.info("Dashboard Studio server idle timeout reached; shutting down.")
                self.shutdown()
                return

    def update_report(
        self,
        new_report: ScanReport | dict[str, Any],
        dashboard_target: Path | None = None,
        source_image_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Atomically update active report, sync dashboard.html on disk, and notify SSE clients."""
        enriched = attach_dashboard_previews(
            new_report,
            source_image_path=source_image_path,
            max_image_pixels=self._config.max_image_pixels,
        )
        with self._lock:
            self._report_dict = enriched
            self._version += 1
            if dashboard_target is not None:
                self._dashboard_file_path = dashboard_target.resolve()
            target_file = self._dashboard_file_path

        if target_file is not None:
            try:
                write_dashboard_file(
                    enriched,
                    output_path=target_file,
                    studio_api_url=self.api_url,
                    studio_token=self.studio_token,
                )
            except PixelGuardError as exc:
                logger.warning("Could not persist updated dashboard to %s: %s", target_file.name, exc)

        return enriched

    def _get_snapshot(self) -> tuple[dict[str, Any], int]:
        with self._lock:
            return self._report_dict, self._version

    def _run_pipeline_on_path(self, image_path: str | Path) -> ScanReport:
        from .pipeline import scan_image

        return scan_image(image_path, config=self._config)

    def _allowed_origins(self) -> set[str]:
        return {
            f"http://127.0.0.1:{self.port}",
            f"http://localhost:{self.port}",
            f"http://[::1]:{self.port}",
        }

    def _make_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        server_ref = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def _is_valid_loopback_host(self) -> bool:
                host_hdr = (self.headers.get("Host") or "").strip().lower()
                if not host_hdr:
                    return True
                if host_hdr.startswith("["):
                    host_only = host_hdr.split("]", 1)[0] + "]"
                else:
                    host_only = host_hdr.split(":", 1)[0]
                return host_only in _LOOPBACK_HOSTS

            def _authorize_request(
                self,
                *,
                query_params: dict[str, list[str]] | None = None,
                require_token_on_null: bool = True,
            ) -> tuple[bool, str | None]:
                """Validate Host header, loopback Origin allowlist, and per-daemon token for file:// origins."""
                if not self._is_valid_loopback_host():
                    return False, None

                origin = self.headers.get("Origin")
                if origin is None:
                    return True, None

                if origin in server_ref._allowed_origins():
                    return True, origin

                if origin == "null":
                    if not require_token_on_null:
                        return True, "null"
                    provided = (self.headers.get("X-Pixel-Guard-Token") or "").strip()
                    if not provided and query_params:
                        provided = (query_params.get("token", [""])[0] or "").strip()
                    if provided and hmac.compare_digest(provided, server_ref.studio_token):
                        return True, "null"
                    return False, None

                return False, None

            def _send_security_headers(
                self,
                allowed_origin: str | None,
                *,
                csp: str | None = None,
                include_cors: bool = True,
            ) -> None:
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
                self.send_header(
                    "Content-Security-Policy",
                    csp or "default-src 'none'; frame-ancestors 'none'",
                )
                if include_cors:
                    if allowed_origin is not None:
                        self.send_header("Access-Control-Allow-Origin", allowed_origin)
                        self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header(
                        "Access-Control-Allow-Headers",
                        "Content-Type, X-Filename, X-Pixel-Guard-Token",
                    )

            def _send_json(
                self,
                status: int,
                payload: dict[str, Any],
                *,
                allowed_origin: str | None = None,
                include_cors: bool = True,
            ) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._send_security_headers(allowed_origin, include_cors=include_cors)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_forbidden(self, code: str = "FORBIDDEN_ORIGIN", message: str = "Request origin or host is not permitted.") -> None:
                self._send_json(
                    403,
                    {"error": True, "error_code": code, "message": message},
                    allowed_origin=None,
                    include_cors=False,
                )

            def do_OPTIONS(self) -> None:  # noqa: N802
                server_ref._touch()
                ok, allowed_origin = self._authorize_request(require_token_on_null=False)
                if not ok:
                    self._send_forbidden()
                    return
                self.send_response(204)
                self._send_security_headers(allowed_origin, include_cors=True)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                server_ref._touch()
                parsed_url = urllib.parse.urlparse(self.path)
                clean_path = parsed_url.path
                query_params = urllib.parse.parse_qs(parsed_url.query)

                require_null_token = clean_path not in {"/", "/dashboard.html", "/index.html", "/api/health"}
                ok, allowed_origin = self._authorize_request(
                    query_params=query_params,
                    require_token_on_null=require_null_token,
                )
                if not ok:
                    self._send_forbidden()
                    return

                if clean_path in {"/", "/dashboard.html", "/index.html"}:
                    report_dict, _ = server_ref._get_snapshot()
                    html_str, csp_header = render_dashboard_html_with_csp(
                        report_dict,
                        studio_api_url=server_ref.api_url,
                        studio_token=server_ref.studio_token,
                    )
                    body = html_str.encode("utf-8")
                    self.send_response(200)
                    self._send_security_headers(allowed_origin, csp=csp_header, include_cors=True)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif clean_path == "/api/health":
                    self._send_json(
                        200,
                        {"status": "ok", "skill": "pixel-guard", "port": server_ref.port},
                        allowed_origin=allowed_origin,
                    )
                elif clean_path == "/api/fixtures":
                    self._send_json(
                        200,
                        {"fixtures": _discover_available_images()},
                        allowed_origin=allowed_origin,
                    )
                elif clean_path == "/api/browse":
                    dir_arg = query_params.get("dir", [""])[0]
                    try:
                        payload = _browse_directory(dir_arg)
                    except ValidationError as exc:
                        self._send_json(
                            403,
                            {
                                "error": True,
                                "error_code": exc.error_code,
                                "message": _sanitize_error_message(str(exc)),
                            },
                            allowed_origin=allowed_origin,
                        )
                        return
                    self._send_json(200, payload, allowed_origin=allowed_origin)
                elif clean_path == "/events":
                    with server_ref._sse_lock:
                        if server_ref._active_sse_clients >= _MAX_SSE_CLIENTS:
                            self._send_json(
                                503,
                                {
                                    "error": True,
                                    "error_code": "SSE_CAPACITY_EXCEEDED",
                                    "message": "Maximum concurrent SSE clients reached.",
                                },
                                allowed_origin=allowed_origin,
                            )
                            return
                        server_ref._active_sse_clients += 1

                    try:
                        self.send_response(200)
                        self._send_security_headers(allowed_origin, include_cors=True)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()
                        last_ver = -1
                        while True:
                            report_dict, ver = server_ref._get_snapshot()
                            if ver != last_ver:
                                last_ver = ver
                                data = json.dumps(report_dict, ensure_ascii=False)
                                msg = f"event: scan_update\ndata: {data}\n\n".encode("utf-8")
                                self.wfile.write(msg)
                                self.wfile.flush()
                            time.sleep(0.4)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                    finally:
                        with server_ref._sse_lock:
                            server_ref._active_sse_clients = max(0, server_ref._active_sse_clients - 1)
                else:
                    self._send_json(
                        404,
                        {"error": True, "message": f"Unknown route: {clean_path}"},
                        allowed_origin=allowed_origin,
                    )

            def do_POST(self) -> None:  # noqa: N802
                server_ref._touch()
                parsed_url = urllib.parse.urlparse(self.path)
                clean_path = parsed_url.path
                query_params = urllib.parse.parse_qs(parsed_url.query)

                ok, allowed_origin = self._authorize_request(
                    query_params=query_params,
                    require_token_on_null=True,
                )
                if not ok:
                    self._send_forbidden()
                    return

                try:
                    content_len = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(
                        400,
                        {"error": True, "error_code": "INVALID_LENGTH", "message": "Invalid Content-Length"},
                        allowed_origin=allowed_origin,
                    )
                    return

                if content_len <= 0 or content_len > _MAX_UPLOAD_BYTES:
                    self._send_json(
                        400,
                        {
                            "error": True,
                            "error_code": "PAYLOAD_SIZE_ERROR",
                            "message": f"Request payload must be between 1 byte and {_MAX_UPLOAD_BYTES} bytes.",
                        },
                        allowed_origin=allowed_origin,
                    )
                    return

                raw_body = self.rfile.read(content_len)

                if clean_path == "/api/scan-path":
                    try:
                        req_json = json.loads(raw_body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._send_json(
                            400,
                            {"error": True, "error_code": "INVALID_JSON", "message": "Malformed JSON body."},
                            allowed_origin=allowed_origin,
                        )
                        return

                    try:
                        jsonschema.validate(instance=req_json, schema=_SCAN_PATH_SCHEMA)
                    except jsonschema.ValidationError as exc:
                        self._send_json(
                            400,
                            {"error": True, "error_code": "INVALID_PAYLOAD", "message": exc.message},
                            allowed_origin=allowed_origin,
                        )
                        return

                    raw_img_path = req_json["image_path"].strip()
                    if not raw_img_path:
                        self._send_json(
                            400,
                            {"error": True, "error_code": "MISSING_PATH", "message": "image_path is required."},
                            allowed_origin=allowed_origin,
                        )
                        return

                    try:
                        candidate_path = _resolve_contained_path(raw_img_path)
                    except ValidationError as exc:
                        self._send_json(
                            403,
                            {
                                "error": True,
                                "error_code": exc.error_code,
                                "message": _sanitize_error_message(str(exc)),
                            },
                            allowed_origin=allowed_origin,
                        )
                        return

                    try:
                        report = server_ref._run_pipeline_on_path(candidate_path)
                        updated_dict = server_ref.update_report(report, source_image_path=candidate_path)
                        self._send_json(200, updated_dict, allowed_origin=allowed_origin)
                    except (ValidationError, OCREngineUnavailableError, PixelGuardError) as exc:
                        err_code = getattr(exc, "error_code", "SCAN_ERROR")
                        self._send_json(
                            400,
                            {
                                "error": True,
                                "error_code": err_code,
                                "message": _sanitize_error_message(str(exc)),
                            },
                            allowed_origin=allowed_origin,
                        )
                    return

                if clean_path == "/api/scan-upload":
                    raw_header_name = urllib.parse.unquote(self.headers.get("X-Filename", "uploaded_image.png"))
                    safe_name = _sanitize_upload_filename(raw_header_name)

                    with tempfile.TemporaryDirectory(prefix="pixel_guard_upload_") as tmp_dir:
                        staged_path = Path(tmp_dir) / safe_name
                        staged_path.write_bytes(raw_body)
                        try:
                            report = server_ref._run_pipeline_on_path(staged_path)
                            repo_sample = (get_project_root() / "tests" / "images" / safe_name).resolve()
                            tests_images_root = (get_project_root() / "tests" / "images").resolve()
                            rel_display_path = (
                                f"tests/images/{safe_name}"
                                if repo_sample.is_relative_to(tests_images_root) and repo_sample.is_file()
                                else safe_name
                            )
                            clean_report = replace(
                                report,
                                image_filename=safe_name,
                                image_path=rel_display_path,
                            )
                            updated_dict = server_ref.update_report(
                                clean_report,
                                source_image_path=staged_path,
                            )
                            self._send_json(200, updated_dict, allowed_origin=allowed_origin)
                        except (ValidationError, OCREngineUnavailableError, PixelGuardError) as exc:
                            err_code = getattr(exc, "error_code", "SCAN_ERROR")
                            self._send_json(
                                400,
                                {
                                    "error": True,
                                    "error_code": err_code,
                                    "message": _sanitize_error_message(str(exc)),
                                },
                                allowed_origin=allowed_origin,
                            )
                    return

                if clean_path == "/api/publish-report":
                    try:
                        payload = json.loads(raw_body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._send_json(
                            400,
                            {"error": True, "error_code": "INVALID_JSON", "message": "Malformed JSON body."},
                            allowed_origin=allowed_origin,
                        )
                        return

                    if not isinstance(payload, dict):
                        self._send_json(
                            400,
                            {"error": True, "error_code": "INVALID_PAYLOAD", "message": "JSON root must be an object."},
                            allowed_origin=allowed_origin,
                        )
                        return

                    if "report" in payload:
                        try:
                            jsonschema.validate(instance=payload, schema=_PUBLISH_WRAPPER_SCHEMA)
                        except jsonschema.ValidationError as exc:
                            self._send_json(
                                400,
                                {"error": True, "error_code": "INVALID_PAYLOAD", "message": exc.message},
                                allowed_origin=allowed_origin,
                            )
                            return
                        raw_report = payload["report"]
                        dash_target_str = payload.get("dashboard_path")
                    else:
                        raw_report = payload
                        dash_target_str = None

                    try:
                        validated_report = _validate_report_payload(raw_report)
                    except ValidationError as exc:
                        self._send_json(
                            400,
                            {
                                "error": True,
                                "error_code": exc.error_code,
                                "message": _sanitize_error_message(str(exc)),
                            },
                            allowed_origin=allowed_origin,
                        )
                        return

                    dash_target: Path | None = None
                    if dash_target_str:
                        candidate_dash = Path(dash_target_str.strip())
                        root = get_project_root().resolve()
                        resolved_dash = (
                            (root / candidate_dash).resolve()
                            if not candidate_dash.is_absolute()
                            else candidate_dash.resolve()
                        )
                        is_current_target = resolved_dash == server_ref._dashboard_file_path
                        is_workspace_html = (
                            resolved_dash.is_relative_to(root)
                            and resolved_dash.suffix.lower() == ".html"
                        )
                        if not (is_current_target or is_workspace_html):
                            self._send_json(
                                403,
                                {
                                    "error": True,
                                    "error_code": "PATH_OUTSIDE_WORKSPACE",
                                    "message": "dashboard_path must be an .html file within the repository workspace.",
                                },
                                allowed_origin=allowed_origin,
                            )
                            return
                        dash_target = resolved_dash

                    updated_dict = server_ref.update_report(validated_report, dashboard_target=dash_target)
                    self._send_json(
                        200,
                        {"status": "published", "image_filename": updated_dict.get("image_filename")},
                        allowed_origin=allowed_origin,
                    )
                    return

                self._send_json(
                    404,
                    {"error": True, "message": f"Unknown POST route: {clean_path}"},
                    allowed_origin=allowed_origin,
                )

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                logger.debug("Dashboard HTTP: " + format, *args)

        return _Handler

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        _clear_studio_token(self.port, self.studio_token)
        threading.Thread(target=self._httpd.shutdown, daemon=True).start()
        self._httpd.server_close()


def _assert_loopback_api_url(api_url: str) -> str:
    """Ensure internal loopback probes/publishes strictly target 127.0.0.1."""
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ValidationError("Studio API URL must target http://127.0.0.1.", error_code="INVALID_LOOPBACK_URL")
    return api_url.rstrip("/")


def _probe_studio_health(api_url: str, timeout: float = 0.35) -> bool:
    """Return True if a pixel-guard Studio server with /api/browse responds at api_url."""
    try:
        base = _assert_loopback_api_url(api_url)
        with urllib.request.urlopen(f"{base}/api/health", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("skill") != "pixel-guard":
                return False
        with urllib.request.urlopen(f"{base}/api/browse", timeout=timeout) as b_resp:
            return b_resp.status == 200
    except (urllib.error.URLError, OSError, ValueError, ValidationError):
        return False


def _is_tcp_port_free(port: int) -> bool:
    """Return True if 127.0.0.1:<port> can be bound cleanly."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _publish_to_running_studio(api_url: str, report: ScanReport, dashboard_path: Path) -> bool:
    """Push a newly generated ScanReport (with image previews) into an already-running Studio daemon."""
    try:
        base = _assert_loopback_api_url(api_url)
    except ValidationError:
        return False

    enriched = attach_dashboard_previews(report)
    root = get_project_root().resolve()
    resolved_dash = dashboard_path.resolve()
    dash_arg: str | None = (
        to_project_relative_path(resolved_dash)
        if resolved_dash.is_relative_to(root) and resolved_dash.suffix.lower() == ".html"
        else None
    )
    body = json.dumps(
        {"report": enriched, "dashboard_path": dash_arg},
        ensure_ascii=False,
    ).encode("utf-8")

    parsed = urllib.parse.urlparse(base)
    token = read_studio_token(parsed.port or DEFAULT_STUDIO_PORT)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Pixel-Guard-Token"] = token

    req = urllib.request.Request(
        f"{base}/api/publish-report",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def ensure_studio_daemon(
    report: ScanReport,
    dashboard_path: str | Path | None = None,
    port: int = DEFAULT_STUDIO_PORT,
    idle_timeout_seconds: float = 3600.0,
) -> str | None:
    """Ensure a local background Studio server is running, automatically skipping busy ports."""
    resolved_dash = (Path(dashboard_path) if dashboard_path is not None else default_dashboard_path()).resolve()

    free_port: int | None = None
    for candidate_port in range(port, port + 20):
        candidate_url = f"http://127.0.0.1:{candidate_port}"
        if _probe_studio_health(candidate_url):
            _publish_to_running_studio(candidate_url, report, resolved_dash)
            return candidate_url
        if free_port is None and _is_tcp_port_free(candidate_port):
            free_port = candidate_port

    if free_port is None:
        return None

    cli_script = get_project_root() / "scripts" / "pixel_guard_cli.py"
    if not cli_script.is_file():
        return None

    api_url = f"http://127.0.0.1:{free_port}"
    daemon_token = secrets.token_urlsafe(32)
    _write_studio_token(free_port, daemon_token)
    child_env = os.environ.copy()
    child_env["PIXEL_GUARD_STUDIO_TOKEN"] = daemon_token

    cmd = [
        sys.executable,
        str(cli_script),
        "--studio-daemon",
        "--studio-port",
        str(free_port),
        "--dashboard-target",
        str(resolved_dash),
        "--studio-idle-timeout",
        str(int(idle_timeout_seconds)),
        "--",
        report.image_path,
    ]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(get_project_root()),
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.debug("Could not spawn background Studio daemon: %s", exc)
        return None

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if _probe_studio_health(api_url, timeout=0.25):
            return api_url
        time.sleep(0.08)

    return None
