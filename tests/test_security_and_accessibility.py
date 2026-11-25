"""Security, authorization, schema validation, decompression-bomb, and WCAG 2.2 AA regression tests."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from mcp_server import handle_jsonrpc_request
from pixel_guard import ScanConfig, ValidationError, render_dashboard_html, scan_image
from pixel_guard.color_science import calculate_wcag_contrast
from pixel_guard.dashboard import DashboardSSEServer, _sanitize_upload_filename
from pixel_guard.metadata import harvest_metadata
from pixel_guard.validator import validate_image_file


def _raw_http_request(
    port: int,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Issue a raw HTTP/1.1 request to 127.0.0.1:<port> with exact custom Host/Origin headers."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        req_headers = dict(headers or {})
        if body is not None and "Content-Length" not in req_headers:
            req_headers["Content-Length"] = str(len(body))
        conn.request(method, path, body=body, headers=req_headers)
        resp = conn.getresponse()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        resp_body = resp.read()
        return resp.status, resp_headers, resp_body
    finally:
        conn.close()


def test_studio_blocks_disallowed_origin_host_and_unauthenticated_null_origin(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify loopback Studio server blocks cross-origin requests, DNS rebinding, and unauthenticated null origins."""
    initial_report = scan_image(synthetic_fixtures["clean_control"])
    dash_file = tmp_path / "dashboard.html"
    server = DashboardSSEServer(initial_report, host="127.0.0.1", port=0, dashboard_file_path=dash_file)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.port

        # 1. External Origin is rejected with 403 and zero CORS allow headers across GET, POST, OPTIONS
        for method, path, body in (
            ("OPTIONS", "/api/scan-path", None),
            ("GET", "/api/browse", None),
            ("GET", "/api/fixtures", None),
            ("GET", "/events", None),
            ("POST", "/api/scan-path", json.dumps({"image_path": "tests/images/clean_control.png"}).encode()),
            ("POST", "/api/scan-upload", synthetic_fixtures["clean_control"].read_bytes()),
            ("POST", "/api/publish-report", json.dumps({"report": initial_report.to_dict()}).encode()),
        ):
            status, hdrs, _ = _raw_http_request(
                port,
                method,
                path,
                headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
                body=body,
            )
            assert status == 403, f"Expected 403 for external origin on {method} {path}, got {status}"
            assert "access-control-allow-origin" not in hdrs

        # 2. Non-loopback Host header (DNS rebinding) is rejected with 403
        status, hdrs, _ = _raw_http_request(
            port,
            "GET",
            "/api/browse",
            headers={"Host": "attacker.example:18765"},
        )
        assert status == 403
        assert "access-control-allow-origin" not in hdrs

        # 3. Sandboxed iframe Origin: null without valid X-Pixel-Guard-Token is rejected with 403
        status, hdrs, _ = _raw_http_request(
            port,
            "POST",
            "/api/scan-path",
            headers={"Origin": "null", "Content-Type": "application/json"},
            body=json.dumps({"image_path": "tests/images/clean_control.png"}).encode(),
        )
        assert status == 403
        assert "access-control-allow-origin" not in hdrs

        status_browse, _, _ = _raw_http_request(port, "GET", "/api/browse", headers={"Origin": "null"})
        assert status_browse == 403

        # 4. Local file:// Origin: null WITH valid per-daemon token succeeds and reflects Origin: null
        status_ok, hdrs_ok, _ = _raw_http_request(
            port,
            "GET",
            "/api/browse",
            headers={"Origin": "null", "X-Pixel-Guard-Token": server.studio_token},
        )
        assert status_ok == 200
        assert hdrs_ok.get("access-control-allow-origin") == "null"
        assert hdrs_ok.get("vary") == "Origin"

        # 5. Same-origin loopback browser tab succeeds and reflects exact loopback origin (never *)
        loopback_origin = f"http://127.0.0.1:{port}"
        status_same, hdrs_same, _ = _raw_http_request(
            port,
            "GET",
            "/api/health",
            headers={"Origin": loopback_origin},
        )
        assert status_same == 200
        assert hdrs_same.get("access-control-allow-origin") == loopback_origin
        assert hdrs_same.get("access-control-allow-origin") != "*"
    finally:
        server.shutdown()


def test_studio_enforces_workspace_path_containment(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify /api/browse, /api/scan-path, and /api/publish-report reject paths outside project root."""
    initial_report = scan_image(synthetic_fixtures["clean_control"])
    dash_file = tmp_path / "dashboard.html"
    server = DashboardSSEServer(initial_report, host="127.0.0.1", port=0, dashboard_file_path=dash_file)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.port

        # 1. GET /api/browse rejects absolute and parent-traversal paths outside workspace
        for bad_dir in ("/etc", "../../../../", str(tmp_path)):
            status, _, body = _raw_http_request(
                port,
                "GET",
                f"/api/browse?dir={urllib.request.quote(bad_dir)}",
            )
            assert status == 403, f"Expected 403 for dir={bad_dir}, got {status}"
            assert json.loads(body.decode("utf-8"))["error_code"] == "PATH_OUTSIDE_WORKSPACE"

        # 2. POST /api/scan-path rejects files outside workspace root
        outside_img = tmp_path / "outside.png"
        Image.new("RGB", (32, 32), color=(255, 255, 255)).save(outside_img, format="PNG")
        for bad_path in (str(outside_img), "../../../../etc/passwd"):
            status, _, body = _raw_http_request(
                port,
                "POST",
                "/api/scan-path",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"image_path": bad_path}).encode(),
            )
            assert status == 403
            assert json.loads(body.decode("utf-8"))["error_code"] == "PATH_OUTSIDE_WORKSPACE"

        # 3. POST /api/publish-report rejects arbitrary write paths outside workspace or non-HTML targets
        outside_write = tmp_path / "arbitrary_overwrite.html"
        for bad_target in (str(outside_write), "README.md", "../../evil.html"):
            status, _, body = _raw_http_request(
                port,
                "POST",
                "/api/publish-report",
                headers={"Content-Type": "application/json"},
                body=json.dumps(
                    {"report": initial_report.to_dict(), "dashboard_path": bad_target}
                ).encode(),
            )
            assert status == 403
            assert json.loads(body.decode("utf-8"))["error_code"] == "PATH_OUTSIDE_WORKSPACE"
        assert not outside_write.exists()
    finally:
        server.shutdown()


def test_studio_strict_json_schema_validation_and_security_headers(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify security headers, SHA-256 CSP, strict schema rejection of undefined keys, and filename sanitization."""
    initial_report = scan_image(synthetic_fixtures["clean_control"])
    dash_file = tmp_path / "dashboard.html"
    server = DashboardSSEServer(initial_report, host="127.0.0.1", port=0, dashboard_file_path=dash_file)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.port

        # 1. HTML response carries strict security headers and SHA-256 hash-pinned CSP
        status, hdrs, html_bytes = _raw_http_request(port, "GET", "/dashboard.html")
        assert status == 200
        assert hdrs.get("x-content-type-options") == "nosniff"
        assert hdrs.get("x-frame-options") == "DENY"
        assert hdrs.get("referrer-policy") == "no-referrer"
        assert "max-age=" in (hdrs.get("strict-transport-security") or "")
        csp = hdrs.get("content-security-policy") or ""
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "script-src 'sha256-" in csp
        assert "script-src 'unsafe-inline'" not in csp

        # Verify CSP hash matches the exact inline application script body
        html_str = html_bytes.decode("utf-8")
        m_script = re.search(
            r'<script id="pixel-guard-app-script">(.*?)</script>',
            html_str,
            re.DOTALL,
        )
        assert m_script is not None
        expected_hash = base64.b64encode(
            hashlib.sha256(m_script.group(1).encode("utf-8")).digest()
        ).decode("ascii")
        assert f"'sha256-{expected_hash}'" in csp

        # 2. Undefined keys and non-dict JSON bodies return 400 (never unhandled 500)
        for path, payload in (
            ("/api/scan-path", [1, 2, 3]),
            ("/api/scan-path", {"image_path": "tests/images/clean_control.png", "unknown_key": True}),
            ("/api/publish-report", ["not", "an", "object"]),
            ("/api/publish-report", {"report": initial_report.to_dict(), "extra_field": "bad"}),
            ("/api/publish-report", {"report": {"skill_name": "pixel-guard"}}),
            (
                "/api/publish-report",
                {
                    "report": {
                        **initial_report.to_dict(),
                        "preview_images": {"original_data_uri": "javascript:alert(1)"},
                    }
                },
            ),
        ):
            st, _, _ = _raw_http_request(
                port,
                "POST",
                path,
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload).encode(),
            )
            assert st == 400, f"Expected 400 on {path} with {payload!r}, got {st}"

        # 3. Filename sanitization strips traversal, null bytes, and control characters
        assert _sanitize_upload_filename("../../etc/passwd\x00.png") == "passwd.png"
        assert _sanitize_upload_filename("..") == "uploaded_image.png"
        assert _sanitize_upload_filename("..hidden") == "hidden.png"
    finally:
        server.shutdown()


def test_mcp_and_config_reject_undefined_keys_and_invalid_types(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify MCP JSON-RPC tools/call and ScanConfig.from_json_file reject undefined keys and invalid types."""
    # MCP tools/list advertises additionalProperties: false
    list_resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
    assert list_resp is not None
    schema = list_resp["result"]["tools"][0]["inputSchema"]
    assert schema.get("additionalProperties") is False

    # Undefined argument key -> -32602
    bad_key_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "inspect_image_security",
                "arguments": {
                    "image_path": str(synthetic_fixtures["clean_control"]),
                    "unexpected_arg": 123,
                },
            },
        }
    )
    assert bad_key_resp is not None
    assert bad_key_resp["error"]["code"] == -32602

    # Wrong argument types -> -32602
    bad_type_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "inspect_image_security",
                "arguments": {
                    "image_path": 12345,
                },
            },
        }
    )
    assert bad_type_resp is not None
    assert bad_type_resp["error"]["code"] == -32602

    # ScanConfig.from_json_file rejects undefined keys, executable overrides, bool-for-int, and out-of-range
    for bad_cfg in (
        {"unknown_threshold": 42},
        {"tesseract_cmd": "/bin/sh"},
        {"wcag_contrast_threshold": True},
        {"max_frames": 999999},
    ):
        cfg_file = tmp_path / "bad_cfg.json"
        cfg_file.write_text(json.dumps(bad_cfg), encoding="utf-8")
        with pytest.raises(ValidationError) as exc_info:
            ScanConfig.from_json_file(cfg_file)
        assert exc_info.value.error_code == "INVALID_CONFIG_JSON"


def test_decompression_bombs_and_file_size_guards(tmp_path: Path) -> None:
    """Verify bounded PNG zlib decompression, multi-frame TIFF pixel ceiling, and raw file size ceiling."""
    # 1. High-ratio PNG zTXt chunk (2 MB repeating text compressed to ~2 KB) is bounded cleanly
    ztxt_png = tmp_path / "ztxt_bomb.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("BombNote", "A" * (2 * 1024 * 1024), zip=True)
    Image.new("RGB", (32, 32), color=(255, 255, 255)).save(ztxt_png, format="PNG", pnginfo=info)

    entries = harvest_metadata(ztxt_png, "PNG", max_chunk_bytes=4096)
    assert entries
    assert all(len(e.content) <= 4096 for e in entries)

    # 2. Multi-page TIFF where Page 0 is small (64x64) and Page 1 exceeds max_image_pixels (200x200 > 10,000)
    bomb_tiff = tmp_path / "multipage_bomb.tiff"
    p0 = Image.new("RGB", (64, 64), color=(255, 255, 255))
    p1 = Image.new("RGB", (200, 200), color=(255, 255, 255))
    p0.save(bomb_tiff, format="TIFF", save_all=True, append_images=[p1])

    strict_px_cfg = ScanConfig(max_image_pixels=10_000)
    with pytest.raises(ValidationError) as exc_px:
        validate_image_file(bomb_tiff, strict_px_cfg)
    assert exc_px.value.error_code == "IMAGE_DIMENSIONS_EXCEEDED"

    # 3. File exceeding max_file_bytes raises FILE_SIZE_EXCEEDED
    strict_sz_cfg = ScanConfig(max_file_bytes=128)
    with pytest.raises(ValidationError) as exc_sz:
        validate_image_file(bomb_tiff, strict_sz_cfg)
    assert exc_sz.value.error_code == "FILE_SIZE_EXCEEDED"


def test_dashboard_wcag_22_aa_contrast_semantics_csp_and_zero_external_assets(
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify WCAG 2.2 AA contrast ratios, semantic landmarks, keyboard hooks, CSP, and URL injection immunity."""
    report = scan_image(synthetic_fixtures["v1d_mixed_doc_hidden_footer"])
    html = render_dashboard_html(
        report,
        studio_api_url='http://evil.example/"; alert(1);//',
    )

    # 1. Crafted non-loopback studio_api_url falls back safely to loopback JSON literal
    assert "alert(1)" not in html
    assert '"http://127.0.0.1:18765"' in html

    # 2. Zero external web font or CDN references and zero decorative theme SVG icons
    for forbidden_external in (
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdnjs.cloudflare.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
    ):
        assert forbidden_external not in html
    theme_match = re.search(r'<div class="theme-selector".*?</div>', html, re.DOTALL)
    assert theme_match is not None
    assert "<svg" not in theme_match.group(0)

    # 3. Strict meta CSP, semantic HTML landmarks, focus indicators, live regions, and text state cues
    for required_markup in (
        '<meta http-equiv="Content-Security-Policy"',
        "script-src 'sha256-",
        'class="skip-link"',
        "<header ",
        "<nav ",
        "<main ",
        "<footer ",
        ":focus-visible",
        ":focus-within",
        'aria-live="polite"',
        "prefers-reduced-motion",
        "[SAFE]",
        "[CRITICAL]",
        "[WARNING]",
        "[SELECTED]",
    ):
        assert required_markup in html, f"Missing required security/accessibility markup: {required_markup}"

    # 4. Mathematical WCAG 2.2 AA contrast verification across Light and Dark themes
    def _h2rgb(hex_color: str) -> tuple[int, int, int]:
        h = hex_color.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    wcag_pairs = [
        # Light mode text (>= 4.5:1) and UI control borders (>= 3.0:1)
        ("#1C1917", "#FAFAF9", 4.5),
        ("#1C1917", "#FFFFFF", 4.5),
        ("#57534E", "#FAFAF9", 4.5),
        ("#57534E", "#FFFFFF", 4.5),
        ("#FFFFFF", "#0F766E", 4.5),
        ("#0F766E", "#FAFAF9", 4.5),
        ("#047857", "#FAFAF9", 4.5),
        ("#047857", "#FFFFFF", 4.5),
        ("#FFFFFF", "#047857", 4.5),
        ("#B45309", "#FAFAF9", 4.5),
        ("#B45309", "#FFFFFF", 4.5),
        ("#FFFFFF", "#B45309", 4.5),
        ("#BE123C", "#FAFAF9", 4.5),
        ("#BE123C", "#FFFFFF", 4.5),
        ("#FFFFFF", "#BE123C", 4.5),
        ("#4338CA", "#FAFAF9", 4.5),
        ("#4338CA", "#FFFFFF", 4.5),
        ("#787774", "#FFFFFF", 3.0),
        ("#787774", "#FAFAF9", 3.0),
        # Dark mode text (>= 4.5:1) and UI control borders (>= 3.0:1)
        ("#ECE8E2", "#0D0E11", 4.5),
        ("#ECE8E2", "#16171D", 4.5),
        ("#9A9895", "#0D0E11", 4.5),
        ("#9A9895", "#16171D", 4.5),
        ("#2DD4BF", "#0D0E11", 4.5),
        ("#2DD4BF", "#16171D", 4.5),
        ("#34D399", "#0D0E11", 4.5),
        ("#34D399", "#16171D", 4.5),
        ("#FBBF24", "#0D0E11", 4.5),
        ("#FBBF24", "#16171D", 4.5),
        ("#FB7185", "#0D0E11", 4.5),
        ("#FB7185", "#16171D", 4.5),
        ("#A5B4FC", "#0D0E11", 4.5),
        ("#A5B4FC", "#16171D", 4.5),
        ("#757785", "#0D0E11", 3.0),
        ("#757785", "#16171D", 3.0),
    ]
    for fg, bg, minimum in wcag_pairs:
        cr = calculate_wcag_contrast(_h2rgb(fg), _h2rgb(bg))
        assert cr >= minimum, f"WCAG 2.2 AA contrast failure for {fg} on {bg}: {cr:.2f}:1 < {minimum}:1"
