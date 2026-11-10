"""Command-line entry logic for pixel-guard."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from .config import OCREngineUnavailableError, PixelGuardError, ScanConfig, ValidationError
from .dashboard import (
    DEFAULT_STUDIO_PORT,
    DashboardSSEServer,
    default_dashboard_path,
    ensure_studio_daemon,
    write_dashboard_file,
)
from .formatter import format_json_report, format_markdown_report
from .pipeline import SKILL_VERSION, scan_image


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for pixel-guard."""
    parser = argparse.ArgumentParser(
        prog="pixel-guard",
        description=(
            "Deterministic pre-flight image sanitizer and hidden prompt-injection scanner. "
            "Operates locally using classical computer vision, color science, and regex heuristics "
            "without invoking any LLM."
        ),
    )
    parser.add_argument(
        "image_path",
        help="Filesystem path to the untrusted image file to inspect.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Primary report output format (default: markdown).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional file path to write the formatted report (defaults to stdout).",
    )
    parser.add_argument(
        "--dashboard",
        nargs="?",
        const="",
        default=None,
        metavar="HTML_PATH",
        help=(
            "Optional custom output path for dashboard.html (by default, dashboard.html "
            "at the project root is written and updated on every scan)."
        ),
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip writing/updating dashboard.html during this scan.",
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Write dashboard.html without starting or updating the background loopback Studio daemon.",
    )
    parser.add_argument(
        "--studio-port",
        type=int,
        default=DEFAULT_STUDIO_PORT,
        help=f"Loopback port for the interactive Dashboard Studio API (default: {DEFAULT_STUDIO_PORT}).",
    )
    parser.add_argument(
        "--sse-port",
        type=int,
        default=None,
        help="Serve the interactive Dashboard Studio in the foreground on 127.0.0.1:<port>.",
    )
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Return exit code 1 on WARNING or exit code 3 on CRITICAL INJECTION DETECTED.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional JSON file overriding threshold parameters.",
    )
    parser.add_argument(
        "--wcag-min",
        type=float,
        default=None,
        help="Override minimum WCAG 2.1 contrast ratio for Section 1 (default: 3.0).",
    )
    parser.add_argument(
        "--delta-e-min",
        type=float,
        default=None,
        help="Override minimum CIEDE2000 Delta-E for Section 1 (default: 15.0).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable diagnostic logging to stderr.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pixel-guard {SKILL_VERSION}",
    )

    # Internal background daemon arguments
    parser.add_argument("--studio-daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dashboard-target", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--studio-idle-timeout", type=float, default=3600.0, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the pixel-guard CLI and return a deterministic POSIX exit code."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )

    try:
        if args.config:
            cfg = ScanConfig.from_json_file(Path(args.config))
        else:
            cfg = ScanConfig.from_env()

        cfg = cfg.with_overrides(
            {
                "wcag_contrast_threshold": args.wcag_min,
                "ciede2000_delta_e_threshold": args.delta_e_min,
            }
        )

        report = scan_image(args.image_path, config=cfg)

        # Internal detached background Studio server entrypoint
        if args.studio_daemon:
            dash_target = Path(args.dashboard_target) if args.dashboard_target else default_dashboard_path()
            server = DashboardSSEServer(
                report,
                host="127.0.0.1",
                port=args.studio_port,
                dashboard_file_path=dash_target,
                config=cfg,
                idle_timeout_seconds=args.studio_idle_timeout,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                server.shutdown()
            return 0

        rendered = (
            format_json_report(report)
            if args.format == "json"
            else format_markdown_report(report)
        )

        if args.output:
            out_path = Path(args.output)
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(rendered, encoding="utf-8")
            except OSError as exc:
                raise PixelGuardError(f"Failed to write output report to {out_path}: {exc}") from exc
        else:
            sys.stdout.write(rendered)

        if not args.no_dashboard:
            active_port = args.sse_port if args.sse_port is not None else args.studio_port
            studio_url = f"http://127.0.0.1:{active_port}"
            target_dash = (
                Path(args.dashboard)
                if (args.dashboard is not None and args.dashboard.strip() != "")
                else default_dashboard_path()
            )
            no_auto_daemon = (
                args.static_only
                or args.sse_port is not None
                or os.getenv("PIXEL_GUARD_NO_AUTO_DAEMON", "").strip() in {"1", "true", "yes"}
            )
            if not no_auto_daemon:
                live_url = ensure_studio_daemon(
                    report,
                    dashboard_path=target_dash,
                    port=args.studio_port,
                )
                if live_url:
                    studio_url = live_url
            write_dashboard_file(
                report,
                output_path=target_dash,
                studio_api_url=studio_url,
            )

        if args.sse_port is not None:
            dash_target = (
                Path(args.dashboard)
                if (args.dashboard is not None and args.dashboard.strip() != "")
                else default_dashboard_path()
            )
            server = DashboardSSEServer(
                report,
                host="127.0.0.1",
                port=args.sse_port,
                dashboard_file_path=dash_target,
                config=cfg,
            )
            sys.stderr.write(
                f"Serving pixel-guard Studio at http://{server.host}:{server.port}/dashboard.html (Ctrl+C to stop)\n"
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                server.shutdown()

        if args.fail_on_findings:
            if report.scan_status == "CRITICAL INJECTION DETECTED":
                return 3
            if report.scan_status == "WARNING":
                return 1
        return 0

    except (ValidationError, OCREngineUnavailableError, PixelGuardError) as exc:
        err_code = getattr(exc, "error_code", "EXECUTION_ERROR")
        if args.format == "json":
            err_payload = {
                "skill_name": "pixel-guard",
                "error": True,
                "error_code": err_code,
                "message": str(exc),
            }
            sys.stderr.write(json.dumps(err_payload, indent=2) + "\n")
        else:
            sys.stderr.write(f"pixel-guard error [{err_code}]: {exc}\n")
        return 2
