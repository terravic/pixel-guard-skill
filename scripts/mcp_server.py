#!/usr/bin/env python3
"""Stdio Model Context Protocol (MCP) server exposing inspect_image_security."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from pixel_guard import (  # noqa: E402
    PixelGuardError,
    SKILL_VERSION,
    ScanConfig,
    format_json_report,
    format_markdown_report,
    scan_image,
    write_dashboard_file,
)


def inspect_image_security(
    image_path: str,
    output_format: str = "markdown",
    generate_dashboard: bool = True,
) -> str:
    """Deterministic pre-flight image sanitizer for hidden text and prompt injections.

    Args:
        image_path: Local filesystem path to the untrusted image file.
        output_format: Report format, either 'markdown' (default) or 'json'.
        generate_dashboard: When true (default), writes/updates dashboard.html at the skill root.
    """
    fmt = output_format.strip().lower()
    if fmt not in {"markdown", "json"}:
        raise ValueError("output_format must be 'markdown' or 'json'")

    cfg = ScanConfig.from_env()
    report = scan_image(image_path, config=cfg)
    if generate_dashboard:
        import os
        from pixel_guard.dashboard import DEFAULT_STUDIO_PORT, default_dashboard_path, ensure_studio_daemon

        target_dash = default_dashboard_path()
        studio_url = f"http://127.0.0.1:{DEFAULT_STUDIO_PORT}"
        if os.getenv("PIXEL_GUARD_NO_AUTO_DAEMON", "").strip() not in {"1", "true", "yes"}:
            live_url = ensure_studio_daemon(report, dashboard_path=target_dash)
            if live_url:
                studio_url = live_url
        write_dashboard_file(report, output_path=target_dash, studio_api_url=studio_url)

    if fmt == "json":
        return format_json_report(report)
    return format_markdown_report(report)


def handle_jsonrpc_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Process a single MCP JSON-RPC 2.0 message for zero-dependency stdio fallback and testing."""
    method = request.get("method", "")
    req_id = request.get("id")

    # Notifications have no id and expect no response
    if req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pixel-guard", "version": SKILL_VERSION},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "inspect_image_security",
                        "description": (
                            "Scan an untrusted image file deterministically (zero LLM calls) for "
                            "low-contrast camouflage, alpha masking, micro-text, metadata payloads, "
                            "and visual prompt injections."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "required": ["image_path"],
                            "properties": {
                                "image_path": {
                                    "type": "string",
                                    "description": "Filesystem path to the image file.",
                                },
                                "output_format": {
                                    "type": "string",
                                    "enum": ["markdown", "json"],
                                    "default": "markdown",
                                },
                                "generate_dashboard": {
                                    "type": "boolean",
                                    "default": False,
                                },
                            },
                        },
                    }
                ]
            },
        }

    if method == "tools/call":
        params = request.get("params") or {}
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if tool_name != "inspect_image_security":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        try:
            output = inspect_image_security(
                image_path=str(arguments.get("image_path", "")),
                output_format=str(arguments.get("output_format", "markdown")),
                generate_dashboard=bool(arguments.get("generate_dashboard", False)),
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": output}],
                    "isError": False,
                },
            }
        except (PixelGuardError, ValueError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"pixel-guard error: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _run_fallback_stdio_loop() -> None:
    """Zero-dependency newline-delimited JSON-RPC 2.0 stdio transport."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_jsonrpc_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def build_sdk_server() -> Any | None:
    """Instantiate official MCP SDK server supporting both mcp 2.x and mcp 1.x."""
    try:
        from mcp.server.mcpserver import MCPServer  # type: ignore[import-not-found]

        srv = MCPServer("pixel-guard")
        srv.tool()(inspect_image_security)
        return srv
    except ImportError:
        pass

    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]

        srv = FastMCP("pixel-guard")
        srv.tool()(inspect_image_security)
        return srv
    except ImportError:
        return None


def main() -> None:
    """Start the pixel-guard MCP server over stdio."""
    sdk_server = build_sdk_server()
    if sdk_server is not None:
        sdk_server.run(transport="stdio")
    else:
        _run_fallback_stdio_loop()


if __name__ == "__main__":
    main()
