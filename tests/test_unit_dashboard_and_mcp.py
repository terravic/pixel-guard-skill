"""Unit tests for standalone HTML dashboard, Load Image Studio API, SSE server, MCP server, and PreToolUse hook."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mcp_server import handle_jsonrpc_request, inspect_image_security
from pixel_guard import scan_image, write_dashboard_file
from pixel_guard.dashboard import DashboardSSEServer
from pre_tool_hook import evaluate_hook_payload


def test_dashboard_html_meets_design_spec_and_load_image_controls(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify generated dashboard.html includes Load Image controls, theme buttons, tokens, and palette."""
    report = scan_image(synthetic_fixtures["v3_micro_text"])
    dash_path = write_dashboard_file(
        report,
        output_path=tmp_path / "dashboard.html",
        studio_api_url="http://127.0.0.1:8765",
    )
    html = dash_path.read_text(encoding="utf-8")

    # 1. Placeholders fully substituted with empirical JSON and Studio URL
    assert "__PIXEL_GUARD_JSON_PAYLOAD__" not in html
    assert "__PIXEL_GUARD_STUDIO_URL__" not in html
    assert "v3_micro_text.png" in html
    assert report.sha256 in html

    # 2. Single Load Image button with native file input present; no duplicate dialog buttons
    assert 'id="load-image-btn"' in html
    assert 'id="load-image-file-input"' in html
    assert "System File Dialog" not in html
    assert 'id="os-file-dialog-label"' not in html
    assert "/api/scan-upload" in html

    # 3. Theme selector SVG icon buttons and persistence attributes
    for btn_id, mode in (
        ('id="theme-btn-light"', 'data-theme-mode="light"'),
        ('id="theme-btn-dark"', 'data-theme-mode="dark"'),
        ('id="theme-btn-system"', 'data-theme-mode="system"'),
    ):
        assert btn_id in html
        assert mode in html
    assert ".theme-btn svg" in html
    assert 'viewBox="0 0 24 24"' in html
    assert "prefers-color-scheme: dark" in html
    assert "localStorage" in html

    # 4. Exact Light and Dark surface/border/text hex tokens
    for required_token in (
        "#FAFAF9",
        "#FFFFFF",
        "#E7E5E4",
        "#1C1917",
        "#787774",
        "#0D0E11",
        "#16171D",
        "#292A30",
        "#ECE8E2",
        "#9A9895",
    ):
        assert required_token in html, f"Missing theme hex token {required_token}"

    # 5. Semantic data visualization palette, typography, title, and embedded image preview + boxes
    for viz_hex in ("#0D9488", "#D97706", "#4F46E5", "#059669", "#E11D48"):
        assert viz_hex in html, f"Missing visualization hex {viz_hex}"
    for font_family in ("DM Sans", "Instrument Serif", "IBM Plex Mono"):
        assert font_family in html, f"Missing required font family {font_family}"
    assert "tabular-nums" in html
    assert "<title>Pixel Guard</title>" in html
    assert '<h1 class="brand-title">Pixel Guard</h1>' in html
    assert "SHA-256:" not in html
    assert "Structural Data Diagram" not in html
    assert "Inspected Image" in html
    assert 'id="inspected-image-el"' in html
    assert 'id="bbox-overlay-svg"' in html
    assert 'id="view-btn-original"' in html
    assert 'id="view-btn-reveal"' in html
    assert 'id="page-nav-group"' in html
    assert 'id="page-prev-btn"' in html
    assert 'id="page-indicator-label"' in html
    assert 'id="page-next-btn"' in html
    assert 'id="pane-processing-status"' in html
    assert "analysis-pane" in html
    assert "enterPendingScanState" in html
    assert "data:image/png;base64," in html
    assert '"image_path": "tests/images/v3_micro_text.png"' in html


def test_dashboard_studio_load_image_upload_scan_path_and_sse(
    tmp_path: Path,
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify Studio server handles Load Image browse/upload, multi-page TIFF frames, Scan Path, disk sync, and SSE."""
    initial_report = scan_image(synthetic_fixtures["clean_control"])
    dash_file = tmp_path / "live_dashboard.html"
    write_dashboard_file(initial_report, output_path=dash_file)

    server = DashboardSSEServer(
        initial_report,
        host="127.0.0.1",
        port=0,
        dashboard_file_path=dash_file,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = server.api_url

        # 1. Health, Browse (tests/images/), and Fixtures discovery endpoints
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=5) as h_resp:
            assert h_resp.status == 200
            assert h_resp.headers.get("Access-Control-Allow-Private-Network") == "true"
            assert json.loads(h_resp.read().decode("utf-8"))["skill"] == "pixel-guard"

        with urllib.request.urlopen(f"{base_url}/api/browse", timeout=5) as b_resp:
            assert b_resp.status == 200
            browse_payload = json.loads(b_resp.read().decode("utf-8"))
            assert browse_payload["current_dir"] == "tests/images"
            assert len(browse_payload["images"]) >= 30

        with urllib.request.urlopen(f"{base_url}/api/fixtures", timeout=5) as f_resp:
            assert f_resp.status == 200
            fixtures_payload = json.loads(f_resp.read().decode("utf-8"))
            assert len(fixtures_payload["fixtures"]) >= 30

        # 2. POST /api/scan-upload (simulating browser Load Image file picker)
        upload_bytes = synthetic_fixtures["v1_low_contrast"].read_bytes()
        up_req = urllib.request.Request(
            f"{base_url}/api/scan-upload",
            data=upload_bytes,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Filename": "v1_low_contrast.png",
            },
            method="POST",
        )
        with urllib.request.urlopen(up_req, timeout=15) as up_resp:
            assert up_resp.status == 200
            up_report = json.loads(up_resp.read().decode("utf-8"))
            assert up_report["image_filename"] == "v1_low_contrast.png"
            assert up_report["scan_status"] == "CRITICAL INJECTION DETECTED"
            assert up_report["quarantined_count"] >= 1

        # Verify disk dashboard.html was updated automatically with the uploaded scan
        assert "v1_low_contrast.png" in dash_file.read_text(encoding="utf-8")

        # 2b. POST /api/scan-upload on multi-page TIFF returns all pages in preview_images.frames
        tiff_bytes = synthetic_fixtures["v7b_multipage_tiff_hidden"].read_bytes()
        tiff_req = urllib.request.Request(
            f"{base_url}/api/scan-upload",
            data=tiff_bytes,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Filename": "v7b_multipage_tiff_hidden.tiff",
            },
            method="POST",
        )
        with urllib.request.urlopen(tiff_req, timeout=15) as tiff_resp:
            assert tiff_resp.status == 200
            tiff_report = json.loads(tiff_resp.read().decode("utf-8"))
            previews = tiff_report["preview_images"]
            assert previews["frame_count"] == 3
            assert len(previews["frames"]) == 3
            assert previews["frames"][0]["original_data_uri"] != previews["frames"][1]["original_data_uri"]
            assert previews["frames"][1]["original_data_uri"] != previews["frames"][2]["original_data_uri"]

        # 3. POST /api/scan-path (programmatic relative path scan)
        path_body = json.dumps({"image_path": "tests/images/v4_exif_injection.jpg"}).encode("utf-8")
        path_req = urllib.request.Request(
            f"{base_url}/api/scan-path",
            data=path_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(path_req, timeout=15) as p_resp:
            assert p_resp.status == 200
            p_report = json.loads(p_resp.read().decode("utf-8"))
            assert p_report["image_filename"] == "v4_exif_injection.jpg"
            assert p_report["image_path"] == "tests/images/v4_exif_injection.jpg"
            assert p_report["scan_status"] == "CRITICAL INJECTION DETECTED"

        # 4. POST /api/scan-upload rejects polyglot file with structured 400 error JSON
        poly_bytes = synthetic_fixtures["corrupt_polyglot"].read_bytes()
        bad_req = urllib.request.Request(
            f"{base_url}/api/scan-upload",
            data=poly_bytes,
            headers={"Content-Type": "application/octet-stream", "X-Filename": "evil.png"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as http_err:
            urllib.request.urlopen(bad_req, timeout=5)
        assert http_err.value.code == 400
        err_json = json.loads(http_err.value.read().decode("utf-8"))
        assert err_json["error"] is True
        assert err_json["error_code"] == "POLYGLOT_OR_INVALID_SIGNATURE"

        # 5. Live SSE stream delivers latest updated report
        with urllib.request.urlopen(f"{base_url}/events", timeout=5) as sse_resp:
            assert sse_resp.status == 200
            first_line = sse_resp.readline().decode("utf-8")
            second_line = sse_resp.readline().decode("utf-8")
            assert first_line.strip() == "event: scan_update"
            parsed = json.loads(second_line[len("data: ") :])
            assert parsed["image_filename"] == "v4_exif_injection.jpg"
    finally:
        server.shutdown()


def test_mcp_server_tool_and_jsonrpc_protocol(synthetic_fixtures: dict[str, Path]) -> None:
    """Verify inspect_image_security direct call and JSON-RPC 2.0 tool execution."""
    md = inspect_image_security(str(synthetic_fixtures["v1_low_contrast"]), output_format="markdown")
    assert "CRITICAL INJECTION DETECTED" in md
    assert "SECTION 2: Quarantined" in md

    list_resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert list_resp is not None
    tools = list_resp["result"]["tools"]
    assert any(t["name"] == "inspect_image_security" for t in tools)

    call_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "inspect_image_security",
                "arguments": {
                    "image_path": str(synthetic_fixtures["clean_control"]),
                    "output_format": "json",
                },
            },
        }
    )
    assert call_resp is not None
    assert call_resp["result"]["isError"] is False
    report_obj = json.loads(call_resp["result"]["content"][0]["text"])
    assert report_obj["scan_status"] == "PASSED"


def test_pre_tool_hook_blocks_adversarial_images_and_allows_clean(
    synthetic_fixtures: dict[str, Path],
) -> None:
    """Verify PreToolUse hook denies unscreened reads of camouflaged/injected images."""
    non_image = evaluate_hook_payload(
        {"toolCall": {"name": "view_file", "args": {"file_path": "README.md"}}}
    )
    assert non_image["decision"] == "allow"

    clean_img = evaluate_hook_payload(
        {
            "toolCall": {
                "name": "view_file",
                "args": {"file_path": str(synthetic_fixtures["clean_control"])},
            }
        }
    )
    assert clean_img["decision"] == "allow"

    attack_img = evaluate_hook_payload(
        {
            "toolCall": {
                "name": "view_file",
                "args": {"file_path": str(synthetic_fixtures["v1_low_contrast"])},
            }
        }
    )
    assert attack_img["decision"] == "deny"
    assert "CRITICAL INJECTION DETECTED" in attack_img["reason"]
