"""Standalone interactive HTML5 dashboard generator and local loopback Studio/SSE server."""

from __future__ import annotations

import base64
from dataclasses import replace
import http.server
import io
import json
import logging
import os
import platform
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

logger = logging.getLogger("pixel_guard.dashboard")

DEFAULT_STUDIO_PORT = 18765
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB ceiling
_MAX_PREVIEW_DIM = 1280
_MAX_PREVIEW_PAGES = 24
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
    pil_img.save(buf, format="PNG", optimize=True)
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
    fw, fh = pil_frame.size
    has_alpha = pil_frame.mode in {"RGBA", "LA", "PA"} or (
        pil_frame.mode == "P" and "transparency" in pil_frame.info
    )
    rgba = np.array(
        pil_frame if pil_frame.mode == "RGBA" else pil_frame.convert("RGBA"),
        dtype=np.uint8,
    )
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
        "width": int(fw),
        "height": int(fh),
        "original_data_uri": orig_uri,
        "reveal_data_uri": reveal_uri,
    }


def build_image_previews(
    image_path: str | Path | None,
    report_dict: dict[str, Any],
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

        with Image.open(path) as img:
            raw_frames = [
                f.copy()
                for _, f in zip(range(_MAX_PREVIEW_PAGES), ImageSequence.Iterator(img))
            ]

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
) -> dict[str, Any]:
    """Return a copy of the report dictionary enriched with preview_images if missing."""
    data = report.to_dict() if isinstance(report, ScanReport) else dict(report)
    if data.get("image_path"):
        data["image_path"] = to_project_relative_path(str(data["image_path"]))
    if not data.get("preview_images"):
        candidate = source_image_path or data.get("image_path")
        previews = build_image_previews(candidate, data)
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

    cwd = Path.cwd()
    if cwd.is_dir():
        for child in sorted(cwd.iterdir()):
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
    """List subdirectories and raster images inside raw_dir using project-relative paths."""
    root = get_project_root()
    default_dir = root / "tests" / "images"
    if not default_dir.is_dir():
        default_dir = root

    if raw_dir and raw_dir.strip():
        target = Path(raw_dir.strip())
        if not target.is_absolute():
            target = (root / target).resolve()
        else:
            target = target.resolve()
    else:
        target = default_dir.resolve()

    if not target.is_dir():
        target = default_dir.resolve()

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


def render_dashboard_html(
    report: ScanReport | dict[str, Any],
    studio_api_url: str = f"http://127.0.0.1:{DEFAULT_STUDIO_PORT}",
    source_image_path: str | Path | None = None,
) -> str:
    """Render self-contained dashboard.html populated with empirical ScanReport data and previews."""
    enriched = attach_dashboard_previews(report, source_image_path=source_image_path)
    payload_json = json.dumps(enriched, ensure_ascii=False).replace("</", "<\\/")
    rendered = DASHBOARD_HTML_TEMPLATE.replace("__PIXEL_GUARD_JSON_PAYLOAD__", payload_json)
    return rendered.replace("__PIXEL_GUARD_STUDIO_URL__", studio_api_url.rstrip("/"))


def write_dashboard_file(
    report: ScanReport | dict[str, Any],
    output_path: str | Path | None = None,
    studio_api_url: str = f"http://127.0.0.1:{DEFAULT_STUDIO_PORT}",
    source_image_path: str | Path | None = None,
) -> Path:
    """Write standalone dashboard.html (defaulting to <skill_root>/dashboard.html) and return its Path."""
    out = Path(output_path) if output_path is not None else default_dashboard_path()
    html = render_dashboard_html(
        report,
        studio_api_url=studio_api_url,
        source_image_path=source_image_path,
    )
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise PixelGuardError(f"Unable to write dashboard file {out}: {exc}") from exc
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
    ) -> None:
        self._report_dict: dict[str, Any] = attach_dashboard_previews(initial_report)
        self._lock = threading.Lock()
        self._version = 1
        self._last_activity = time.monotonic()
        self._dashboard_file_path = (
            dashboard_file_path.resolve() if dashboard_file_path else default_dashboard_path()
        )
        self._config = config or ScanConfig.from_env()
        self._idle_timeout = idle_timeout_seconds
        self.host = host
        self._httpd = http.server.ThreadingHTTPServer((host, port), self._make_handler())
        self.port = int(self._httpd.server_address[1])
        self.api_url = f"http://{self.host}:{self.port}"

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
        enriched = attach_dashboard_previews(new_report, source_image_path=source_image_path)
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
                )
            except PixelGuardError as exc:
                logger.warning("Could not persist updated dashboard to %s: %s", target_file, exc)

        return enriched

    def _get_snapshot(self) -> tuple[dict[str, Any], int]:
        with self._lock:
            return self._report_dict, self._version

    def _run_pipeline_on_path(self, image_path: str | Path) -> ScanReport:
        from .pipeline import scan_image

        return scan_image(image_path, config=self._config)

    def _make_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        server_ref = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def _send_cors_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802
                server_ref._touch()
                self.send_response(204)
                self._send_cors_headers()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                server_ref._touch()
                parsed_url = urllib.parse.urlparse(self.path)
                clean_path = parsed_url.path
                query_params = urllib.parse.parse_qs(parsed_url.query)

                if clean_path in {"/", "/dashboard.html", "/index.html"}:
                    report_dict, _ = server_ref._get_snapshot()
                    body = render_dashboard_html(
                        report_dict,
                        studio_api_url=server_ref.api_url,
                    ).encode("utf-8")
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif clean_path == "/api/health":
                    self._send_json(
                        200,
                        {"status": "ok", "skill": "pixel-guard", "port": server_ref.port},
                    )
                elif clean_path == "/api/fixtures":
                    self._send_json(200, {"fixtures": _discover_available_images()})
                elif clean_path == "/api/browse":
                    dir_arg = query_params.get("dir", [""])[0]
                    self._send_json(200, _browse_directory(dir_arg))
                elif clean_path == "/events":
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    last_ver = -1
                    try:
                        while True:
                            server_ref._touch()
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
                else:
                    self._send_json(404, {"error": True, "message": f"Unknown route: {clean_path}"})

            def do_POST(self) -> None:  # noqa: N802
                server_ref._touch()
                clean_path = self.path.split("?", 1)[0]

                try:
                    content_len = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"error": True, "error_code": "INVALID_LENGTH", "message": "Invalid Content-Length"})
                    return

                if content_len <= 0 or content_len > _MAX_UPLOAD_BYTES:
                    self._send_json(
                        400,
                        {
                            "error": True,
                            "error_code": "PAYLOAD_SIZE_ERROR",
                            "message": f"Request payload must be between 1 byte and {_MAX_UPLOAD_BYTES} bytes.",
                        },
                    )
                    return

                raw_body = self.rfile.read(content_len)

                if clean_path == "/api/scan-path":
                    try:
                        req_json = json.loads(raw_body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._send_json(400, {"error": True, "error_code": "INVALID_JSON", "message": "Malformed JSON body."})
                        return

                    raw_img_path = str(req_json.get("image_path", "")).strip()
                    if not raw_img_path:
                        self._send_json(400, {"error": True, "error_code": "MISSING_PATH", "message": "image_path is required."})
                        return

                    candidate_path = Path(raw_img_path)
                    if not candidate_path.is_absolute():
                        cwd_try = (Path.cwd() / candidate_path).resolve()
                        root_try = (get_project_root() / candidate_path).resolve()
                        candidate_path = cwd_try if cwd_try.exists() else root_try

                    try:
                        report = server_ref._run_pipeline_on_path(candidate_path)
                        updated_dict = server_ref.update_report(report, source_image_path=candidate_path)
                        self._send_json(200, updated_dict)
                    except (ValidationError, OCREngineUnavailableError, PixelGuardError) as exc:
                        err_code = getattr(exc, "error_code", "SCAN_ERROR")
                        self._send_json(400, {"error": True, "error_code": err_code, "message": str(exc)})
                    return

                if clean_path == "/api/scan-upload":
                    raw_header_name = urllib.parse.unquote(self.headers.get("X-Filename", "uploaded_image.png"))
                    safe_name = Path(raw_header_name).name or "uploaded_image.png"
                    if Path(safe_name).suffix.lower() not in _SUPPORTED_EXTS:
                        safe_name = safe_name + ".png"

                    with tempfile.TemporaryDirectory(prefix="pixel_guard_upload_") as tmp_dir:
                        staged_path = Path(tmp_dir) / safe_name
                        staged_path.write_bytes(raw_body)
                        try:
                            report = server_ref._run_pipeline_on_path(staged_path)
                            clean_report = replace(
                                report,
                                image_filename=safe_name,
                                image_path=f"[Loaded via Dashboard] {safe_name}",
                            )
                            updated_dict = server_ref.update_report(
                                clean_report,
                                source_image_path=staged_path,
                            )
                            self._send_json(200, updated_dict)
                        except (ValidationError, OCREngineUnavailableError, PixelGuardError) as exc:
                            err_code = getattr(exc, "error_code", "SCAN_ERROR")
                            self._send_json(400, {"error": True, "error_code": err_code, "message": str(exc)})
                    return

                if clean_path == "/api/publish-report":
                    try:
                        payload = json.loads(raw_body.decode("utf-8"))
                        report_data = payload.get("report") if "report" in payload else payload
                        dash_target_str = payload.get("dashboard_path")
                        dash_target = Path(dash_target_str) if dash_target_str else None
                        updated_dict = server_ref.update_report(report_data, dashboard_target=dash_target)
                        self._send_json(200, {"status": "published", "image_filename": updated_dict.get("image_filename")})
                    except Exception as exc:  # noqa: BLE001
                        self._send_json(400, {"error": True, "error_code": "PUBLISH_FAILED", "message": str(exc)})
                    return

                self._send_json(404, {"error": True, "message": f"Unknown POST route: {clean_path}"})

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                logger.debug("Dashboard HTTP: " + format, *args)

        return _Handler

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        threading.Thread(target=self._httpd.shutdown, daemon=True).start()
        self._httpd.server_close()


def _probe_studio_health(api_url: str, timeout: float = 0.35) -> bool:
    """Return True if a pixel-guard Studio server with /api/browse responds at api_url."""
    try:
        with urllib.request.urlopen(f"{api_url}/api/health", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("skill") != "pixel-guard":
                return False
        with urllib.request.urlopen(f"{api_url}/api/browse", timeout=timeout) as b_resp:
            return b_resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
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
    enriched = attach_dashboard_previews(report)
    body = json.dumps(
        {"report": enriched, "dashboard_path": str(dashboard_path.resolve())},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url}/api/publish-report",
        data=body,
        headers={"Content-Type": "application/json"},
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
    cmd = [
        sys.executable,
        str(cli_script),
        report.image_path,
        "--studio-daemon",
        "--studio-port",
        str(free_port),
        "--dashboard-target",
        str(resolved_dash),
        "--studio-idle-timeout",
        str(int(idle_timeout_seconds)),
    ]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(get_project_root()),
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
