# Agent Harness Integration Guide

`pixel-guard` exposes four integration surfaces for AI agent harnesses: **Skill Manifest (`SKILL.md`)**, **Lifecycle Pre-Tool Hook (`assets/hooks.json`)**, **Model Context Protocol Server (`assets/mcp_config.json`)**, and **Standalone CLI (`scripts/pixel_guard_cli.py`)**.

---

## 1. Skill Plug-In Discovery (`SKILL.md`)

Place or symlink the `pixel-guard` directory inside your workspace skill directory using relative paths:

- `.agents/skills/pixel-guard/`
- `skills/pixel-guard/`

When a user provides a plain-text path to an image file, the agent reads `SKILL.md`, invokes `scripts/pixel_guard_cli.py`, forwards only Section 1 verified text into downstream context, and reports any Section 2 quarantined findings.

---

## 2. Automated Lifecycle Interception (`assets/hooks.json`)

To enforce deterministic gating if an agent attempts to read an untrusted image directly via `view_file`, `read_file`, `Read`, or `open_file`, copy `assets/hooks.json` into your harness hook configuration.

### Hook Payload Behavior (`scripts/pre_tool_hook.py`)

1. Reads the JSON `PreToolUse` event from `stdin` (supporting `toolCall.name`/`toolCall.args` and `tool_name`/`tool_input`).
2. Checks whether the target tool targets a raster image path (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.bmp`, `.tif`, `.tiff`, `.pbm`, `.pgm`, `.ppm`).
3. Runs `pixel-guard` on the target image path:
   - If `CRITICAL INJECTION DETECTED` or `WARNING` (hidden or suspicious text found), returns `{"decision": "deny", "reason": "..."}` containing the full `pixel-guard` Dual-Section summary so raw adversarial pixels never enter the multimodal vision encoder.
   - If `PASSED` (clean image) and `PIXEL_GUARD_HOOK_MODE=strict_airgap`, returns `{"decision": "deny", "reason": "..."}` providing the verified Section 1 text directly; under default `PIXEL_GUARD_HOOK_MODE=gate_threats`, returns `{"decision": "allow"}` after confirming zero hidden or adversarial anomalies.

---

## 3. Model Context Protocol Server (`assets/mcp_config.json`)

Register `scripts/mcp_server.py` using `assets/mcp_config.json` to expose the `inspect_image_security` tool over stdio transport:

```json
{
  "mcpServers": {
    "pixel-guard": {
      "command": "python3",
      "args": ["scripts/mcp_server.py"],
      "env": {
        "PIXEL_GUARD_WCAG_MIN": "3.0",
        "PIXEL_GUARD_DELTA_E_MIN": "15.0",
        "PIXEL_GUARD_ALPHA_MIN": "0.30",
        "PIXEL_GUARD_MIN_HEIGHT_PX": "8"
      }
    }
  }
}
```

### Exposed MCP Tool Signature

- **Tool Name:** `inspect_image_security`
- **Arguments:**
  - `image_path` (`string`, required): Relative or local filesystem path to the untrusted image.
  - `output_format` (`string`, optional, default `"markdown"`): `"markdown"` or `"json"`.
  - `generate_dashboard` (`boolean`, optional, default `true`): Write and update `dashboard.html` at the skill root.

---

## 4. Environment Variable Configuration Reference

Runtime thresholds can be configured via environment variables without modifying code:

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `PIXEL_GUARD_WCAG_MIN` | `3.0` | Minimum WCAG 2.1 contrast ratio for Section 1 human visibility. |
| `PIXEL_GUARD_DELTA_E_MIN` | `15.0` | Minimum CIEDE2000 perceptual color difference for Section 1. |
| `PIXEL_GUARD_ALPHA_MIN` | `0.30` | Minimum mean stroke opacity (`0.0` to `1.0`) for Section 1. |
| `PIXEL_GUARD_MIN_HEIGHT_PX` | `8` | Minimum bounding-box pixel height before flagging `MICRO_TEXT_ANOMALY`. |
| `PIXEL_GUARD_ENTROPY_MAX` | `4.7` | Maximum Shannon entropy (bits/char) on unspaced tokens `>= 24` chars. |
| `PIXEL_GUARD_MAX_PIXELS` | `36000000` | Maximum allowed pixel count (`width * height`) before rejecting decompression bombs. |
| `PIXEL_GUARD_MAX_FRAMES` | `24` | Maximum distinct pages or frames analyzed in multi-frame containers. |
| `PIXEL_GUARD_MAX_OCR_DIM` | `1600` | Maximum working pixel dimension for full-frame OCR passes before 1x coordinate remapping. |
| `PIXEL_GUARD_OCR_WORKERS` | `4` | Thread pool concurrency for local Tesseract passes. |
| `PIXEL_GUARD_OCR_TIMEOUT_S` | `10.0` | Per-invocation timeout in seconds for local Tesseract subprocess execution. |
| `PIXEL_GUARD_TESSERACT_CMD` | Auto-detected | Optional explicit path or command name for the `tesseract` binary. |
| `PIXEL_GUARD_HOOK_MODE` | `gate_threats` | `gate_threats` (block threats/hidden text) or `strict_airgap` (always substitute text report). |
| `PIXEL_GUARD_SYSTEM_THEME` | Auto-detected | Optional explicit fallback theme (`light` or `dark`) embedded into `dashboard.html`. |
