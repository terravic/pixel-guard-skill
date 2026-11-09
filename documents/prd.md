# Product Requirements Document: pixel-guard

**Product Identifier:** `pixel-guard`  
**Version:** 1.0.0  
**Status:** Production Specification  
**Classification:** Deterministic Multimodal Pre-Flight Security Skill  
**License:** Apache-2.0

---

## 1. Overview and Problem Statement

Autonomous AI agent harnesses accept multimodal inputs, allowing end users and external workflows to submit screenshots, scanned clinical forms, financial invoices, and technical diagrams alongside natural-language prompts. Passing untrusted raster images directly into Multimodal Large Language Models (MLLMs) exposes the agent runtime to Visual Indirect Prompt Injections (V-IPI) and container-level instruction smuggling.

Adversaries embed instructions that remain imperceptible during human visual review yet survive vision-encoder normalization, contrast stretching, alpha flattening, or metadata ingestion. Common vectors include sub-threshold foreground-to-background contrast (for example, `#FAFAFA` glyphs on a `#FFFFFF` background), near-zero or zero-alpha channel layers, micro-typography (`2px` to `6px` height), non-pixel metadata payloads (`EXIF`, `XMP`, `IPTC`, PNG text chunks), inactive animation frames, embossed spatial-frequency watermarks, and visible prompt-override syntax containing Markdown exfiltration URLs.

`pixel-guard` mitigates these threats through an air-gapped, deterministic pre-flight analysis pipeline written in Python. The skill uses classical computer vision, local Optical Character Recognition (OCR), mathematical color science (WCAG 2.1 relative luminance contrast and CIEDE2000 perceptual color difference), and rule-based threat heuristics. No local or remote LLM is invoked at any stage of image inspection. Every analyzed asset produces a strict two-section report separating human-verified visible text (Section 1) from quarantined, camouflaged, or adversarial findings (Section 2), with optional JSON serialization and standalone interactive HTML dashboard telemetry.

---

## 2. User Stories and Scope

### 2.1 Target Personas and User Stories

| Persona ID | Target Audience | User Story | Acceptance Outcome |
| :--- | :--- | :--- | :--- |
| **US-01** | Non-Technical Enterprise / Clinical Analyst | As an analyst reviewing synthetic laboratory batch records or scanned vendor invoices inside an agent chat session, I want the agent to automatically screen uploaded images for hidden instructions before reading them so that concealed commands cannot hijack my session or exfiltrate workspace data. | Agent executes `pixel-guard` first, consumes only Section 1 verified text, and surfaces any Section 2 quarantine alerts in plain language. |
| **US-02** | AI Platform / Agent Security Engineer | As a security engineer deploying multimodal agents on the Gemini Enterprise Agent Platform, Antigravity, or Claude Code, I want a deterministic `PreToolUse` hook and MCP server (`inspect_image_security`) that blocks direct MLLM ingestion of unscreened image bytes. | Direct image-read tool calls are gated until `pixel-guard` completes with deterministic exit codes and schema-validated telemetry. |
| **US-03** | Healthcare and Life Sciences (HCLS) Compliance Officer | As an HCLS compliance officer, I require that pre-flight document screening runs 100% locally with zero external API calls, zero telemetry, and strict separation of anomalous metadata so regulated clinical workflows maintain complete data residency. | Zero outbound sockets are opened; processing stays within local CPU/RAM budgets and emits auditable provenance records. |
| **US-04** | Forensic / Security Operations Reviewer | As an incident responder triage-testing a suspicious image attachment, I want an interactive, offline-capable HTML dashboard displaying active vision passes, spatial bounding boxes, WCAG contrast ratios, CIEDE2000 color deltas, and matched threat rules. | Running `--dashboard` produces a self-contained `dashboard.html` viewable offline in Light, Dark, or System themes. |

### 2.2 In-Scope Capabilities

1. **Supported Raster Formats:** JPEG (`.jpg`, `.jpeg`), PNG (`.png`, including RGBA and APNG), WebP (`.webp`), BMP (`.bmp`), GIF (`.gif`, static and multi-frame), TIFF (`.tif`, `.tiff`, single and multi-page), and Netpbm (`.pbm`, `.pgm`, `.ppm`).
2. **Binary Signature and Polyglot Validation:** True magic-byte verification, script/executable polyglot header rejection, and pixel-count decompression bomb protection.
3. **Container Metadata Harvesting:** Extraction and sanitization of EXIF IFDs (`0th`, `Exif`, `1st`, `GPS`, `Interop`), PNG textual chunks (`tEXt`, `zTXt`, `iTXt`), XMP XML packets, IPTC descriptors, and GIF comment extensions.
4. **Six-Pass Deterministic Computer Vision Decomposition:**
   - Pass A (`baseline`): Standard white-composited RGB grayscale baseline.
   - Pass B (`clahe_contrast`): $35 \times 35$ local median background subtraction with local peak-envelope anti-aliased normalization.
   - Pass C (`perceptual_channels`): Contrast-stretched CIE $L^*a^*b^*$ chrominance (`a*`, `b*`) and HSV saturation (`S`) channels to expose iso-luminant hue camouflage.
   - Pass D (`alpha_isolation`): Partial-alpha perturbation binarization ($0 < \alpha < 255$) plus raw uncomposited RGB extraction under transparent masks ($\alpha < 0.30$).
   - Pass E (`edge_frequency`): Sobel morphological gradient enhancement to expose embossed or high-frequency residual glyphs.
   - Pass F (`micro_upscale`): $4\times$ bicubic (`INTER_CUBIC`) super-resolution on micro-component regions to recover `2px` to `7px` text.
5. **Multi-Frame Container Decomposition:** Perceptual pixel-difference iteration across multi-frame GIF, TIFF, PNG, and WebP containers to detect flash-frame injections without redundant OCR on static frames.
6. **Air-Gapped Local OCR and Spatial Deduplication:** Concurrent local Tesseract 5 execution (with optional offline EasyOCR adapter) and spatial Intersection-over-Union (IoU) and baseline-containment line consolidation.
7. **Mathematical Visibility Profiling:** Polarity-aware foreground stroke and 3-pixel dilated background collar sampling, WCAG 2.1 contrast ratio computation, and CIEDE2000 ($\Delta E^*_{00}$) color-difference scoring.
8. **Deterministic Threat Heuristic Engine:** Compiled regular-expression catalog for instruction overrides, system role spoofing, persona jailbreaks, Markdown image exfiltration, shell/script injection, Base64/Hex/URL payload decoding, and Shannon entropy anomaly scoring.
9. **Multi-Format Reporting and Harness Integrations:** Dual-Section Markdown report, JSON Schema validated report, standalone `dashboard.html` (with optional SSE live refresh), CLI script, stdio MCP server, and `PreToolUse` lifecycle hook.

### 2.3 Out-of-Scope Boundaries

1. **Zero LLM Usage:** Neither cloud nor local generative language/vision models may be called to transcribe, classify, or summarize images.
2. **Destructive Image Inpainting:** `pixel-guard` extracts, classifies, and quarantines text; it does not overwrite or reconstruct source image pixels.
3. **Cryptographic Steganalysis:** Breaking encrypted LSB payloads (such as AES-encrypted bitstreams lacking visual glyph structure or container text) is outside scope because MLLM vision encoders do not decrypt cryptographic bitstreams.
4. **Audio/Video Stream Decoding:** Container video formats (`.mp4`, `.mkv`, `.avi`) and audio files are outside scope.

---

## 3. Technical Architecture

### 3.1 Harness Integration Sequence Diagram

```text
+---------------+      +-----------------------+      +-------------------------+      +--------------------+
|   End User    |      |     Agent Harness     |      |  pixel-guard Pre-Flight |      |   Downstream LLM   |
|               |      | (Skill / Hook / MCP)  |      |  (Deterministic Python) |      |  (Text Context)    |
+-------+-------+      +-----------+-----------+      +------------+------------+      +---------+----------+
        |                          |                               |                             |
        | 1. Submit image path     |                               |                             |
        |------------------------->|                               |                             |
        |                          | 2. PreToolUse Hook / SKILL.md |                             |
        |                          |    intercepts raw image read  |                             |
        |                          |------------------------------>|                             |
        |                          |                               | 3. Magic-byte & polyglot    |
        |                          |                               |    validation               |
        |                          |                               | 4. Harvest EXIF/PNG/XMP     |
        |                          |                               | 5. Generate CV Passes A-F   |
        |                          |                               |    + multi-frame diff       |
        |                          |                               | 6. Parallel local Tesseract |
        |                          |                               | 7. WCAG CR & CIEDE2000 math |
        |                          |                               | 8. Regex, Base64 & entropy  |
        |                          |                               |                             |
        |                          | 9. Dual-Section Report        |                             |
        |                          |    (Sec 1 Safe / Sec 2 Quar.) |                             |
        |                          |<------------------------------|                             |
        |                          |                               |                             |
        |                          | 10. If CRITICAL/WARNING:      |                             |
        | 11. Quarantine alert &   |     Quarantine Sec 2; pass    |                             |
        |     safe workflow output |     ONLY Sec 1 verified text  |                             |
        |<-------------------------|------------------------------------------------------------>|
```

### 3.2 Six-Stage Internal Processing Flow

```text
[Input Image Path]
        |
        v
+-----------------------------------------------------------------------+
| STAGE 1: INGESTION, MAGIC-BYTE VALIDATION & METADATA HARVESTING       |
|  - Verify header signature (JPEG/PNG/WEBP/BMP/GIF/TIFF/PNM)           |
|  - Block HTML/JS/script/ELF/PE polyglots & decompression bombs        |
|  - Extract EXIF IFDs, PNG tEXt/zTXt/iTXt, XMP XML, IPTC, GIF comments |
+-----------------------------------+-----------------------------------+
                                    |
                 +------------------+------------------+
                 |                                     |
                 v                                     |
+-----------------------------------+                  |
| STAGE 2: MULTI-FRAME & CV PASSES  |                  |
|  - Deduplicate animation frames   |                  |
|  - Pass A: Baseline Grayscale     |                  |
|  - Pass B: Median Sub + Envelope  |                  |
|  - Pass C: LAB (a*,b*) & HSV (S)  |                  |
|  - Pass D: Partial & Zero Alpha   |                  |
|  - Pass E: Morphological Edge     |                  |
|  - Pass F: 4x Cubic Micro-Text    |                  |
+-----------------+-----------------+                  |
                  |                                    |
                  v                                    |
+-----------------------------------+                  |
| STAGE 3: PARALLEL LOCAL OCR       |                  |
|  - Channel variance gatekeeper    |                  |
|  - ThreadPool Tesseract 5 TSV     |                  |
|  - Inverse scale bbox mapping     |                  |
|  - Cross-pass IoU deduplication   |                  |
+-----------------+-----------------+                  |
                  |                                    |
                  v                                    |
+-----------------------------------+                  |
| STAGE 4: COLOR SCIENCE PROFILING  |                  |
|  - Polarity-oriented glyph mask   |                  |
|  - 3px dilated local collar RGB   |                  |
|  - WCAG 2.1 Contrast Ratio        |                  |
|  - CIEDE2000 Perceptual Delta-E   |                  |
|  - Alpha opacity & height checks  |                  |
+-----------------+-----------------+                  |
                  |                                    |
                  +-----------------+------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
| STAGE 5: DETERMINISTIC THREAT HEURISTICS & ENTROPY ENGINE             |
|  - Instruction overrides, system role spoofing, persona jailbreaks    |
|  - Markdown image exfiltration & suspicious query URL detection       |
|  - Command/script signatures (curl, wget, eval, bash, <script>)       |
|  - Base64/Hex/URL decoding + recursive re-scan + Shannon entropy      |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
| STAGE 6: BIFURCATED OUTPUT & TELEMETRY GENERATION                     |
|  - Section 1: Human-Visible & Threat-Clean Text                       |
|  - Section 2: Quarantined / Hidden / Suspicious Findings              |
|  - Output Formats: Markdown, Schema-Validated JSON, dashboard.html    |
+-----------------------------------------------------------------------+
```

### 3.3 Component Responsibilities

- `SKILL.md`: Agent harness entry manifest instructing the orchestrating model on mandatory pre-flight invocation, safe consumption of Section 1, and quarantine escalation for Section 2.
- `scripts/pixel_guard_cli.py`: Command-line interface supporting Markdown, JSON, standalone HTML dashboard generation, SSE live streaming, custom threshold overrides, and strict CI exit codes.
- `scripts/mcp_server.py`: Stdio Model Context Protocol server exposing `inspect_image_security` via `FastMCP` with a built-in zero-dependency JSON-RPC 2.0 fallback.
- `scripts/pre_tool_hook.py`: Lifecycle `PreToolUse` gate reading camelCase hook payloads on `stdin` and intercepting unscreened image reads.
- `scripts/pixel_guard/`: Modular core library (`config.py`, `models.py`, `validator.py`, `metadata.py`, `preprocessor.py`, `ocr_engine.py`, `color_science.py`, `heuristics.py`, `formatter.py`, `dashboard.py`).
- `assets/`: Static schemas (`report_schema.json`), HTML template (`dashboard_template.html`), and harness configurations (`mcp_config.json`, `hooks.json`, `plugin.json`).

---

## 4. Functional Requirements

### 4.1 Input Ingestion and Structural Validation (FR-01 to FR-03)

- **FR-01 (Magic-Byte Verification):** The validator must inspect raw leading file bytes to confirm authentic signatures for JPEG (`FF D8 FF`), PNG (`89 50 4E 47 0D 0A 1A 0A`), GIF (`47 49 46 38`), BMP (`42 4D`), WebP (`52 49 46 46 ... 57 45 42 50`), TIFF (`49 49 2A 00` or `4D 4D 00 2A`), and Netpbm (`P1` through `P6`). Extension-header mismatches or unrecognized signatures must raise `ValidationError` and return exit code `2`.
- **FR-02 (Polyglot Rejection):** The validator must scan the initial 4 KB and trailing 4 KB of the file for embedded script or executable markers (`<!DOCTYPE`, `<html`, `<script`, `<?php`, `#!`, ELF `\x7fELF`, PE `MZ` outside BMP context) and reject suspect polyglots with exit code `2`.
- **FR-03 (Decompression Bomb Guard):** Images exceeding `PIXEL_GUARD_MAX_PIXELS` (default `36,000,000` pixels) or corrupted raster streams failing `Image.verify()` must be rejected prior to full buffer allocation with exit code `2`.

### 4.2 Container Metadata and Multi-Frame Extraction (FR-04 to FR-05)

- **FR-04 (Metadata Harvesting):** All non-empty textual values in EXIF IFDs (`ImageDescription`, `UserComment`, `Artist`, `Copyright`, `Software`, `XPComment`, `XPSubject`, `DocumentName`, `MakerNote` printable strings), PNG chunks (`tEXt`, `zTXt`, `iTXt`), XMP XML packets, IPTC records, and GIF comment blocks must be extracted, stripped of non-printable control characters, labeled with provenance (`EXIF:<Tag>`, `PNG:<Key>`, `XMP`, `GIF:Comment`), and routed through the Stage 5 threat analyzer.
- **FR-05 (Multi-Frame Decomposition):** For animated or multi-page containers (GIF, WebP, APNG, TIFF), the preprocessor must iterate up to `PIXEL_GUARD_MAX_FRAMES` (default `8`) frames, skipping consecutive frames whose mean absolute grayscale pixel delta is below `1.0` intensity unit, and tag any text discovered on `frame_index > 0` with `INACTIVE_FRAME_OBFUSCATION`.

### 4.3 Computer Vision Multi-Pass and Local OCR (FR-06 to FR-08)

- **FR-06 (Deterministic Vision Passes):** Each distinct frame must undergo six deterministic transformations:
  1. `baseline`: RGBA composited over opaque `#FFFFFF`, converted to `uint8` grayscale.
  2. `clahe_contrast`: Halo-free $35 \times 35$ local median background subtraction (`|gray - medianBlur(gray, 35)|`) normalized against a $25 \times 25$ dilated local peak envelope to preserve grayscale anti-aliasing across both high-contrast and micro-contrast strokes.
  3. `perceptual_channels`: CIE $L^*a^*b^*$ `a*` and `b*` channels and HSV `S` channel normalized via local median deviation, gated off when cross-channel RGB difference `< 3`.
  4. `alpha_isolation`: Partial-alpha mask ($0 < \alpha < 255$ mapped to dark strokes on white) and uncomposited raw RGB grayscale masked to pixels where $\alpha < 77$ (`30%` opacity).
  5. `edge_frequency`: Combined Sobel gradient magnitude, $3 \times 3$ morphological closing, percentile normalization, and inversion to dark strokes on white background.
  6. `micro_upscale`: Candidate micro-glyph regions (connected components with height `2px` to `9px`) locally normalized and upscaled $4\times$ via `INTER_CUBIC`.
- **FR-07 (Air-Gapped Parallel OCR):** Active passes passing fast connected-component variance gating must be processed concurrently via local Tesseract (`--oem 3` LSTM) to extract word-level tokens, confidences, and bounding boxes `(x, y, w, h)` mapped back to $1\times$ native image coordinates.
- **FR-08 (Cross-Pass Line Consolidation and Deduplication):** Horizontally adjacent words on the same baseline are merged into phrase bounding boxes. Detections across passes sharing spatial IoU `>= 0.50` (or vertical overlap `>= 0.60` with normalized token similarity `>= 0.75`) are deduplicated, preserving `baseline` as `origin_pass` whenever the text was already legible in Pass A.

### 4.4 Color Science and Visibility Classification (FR-09 to FR-10)

- **FR-09 (Foreground and Local Collar Profiling):** Within each region's native RGBA crop, glyph strokes ($M_{fg}$) are segmented via polarity-oriented thresholding anchored against outer border pixels. Foreground color ($C_{fg}$) is the median RGB of $M_{fg}$; local background color ($C_{bg}$) is the median RGB of the 3-pixel morphologically dilated collar ($M_{dilated} \setminus M_{fg}$). Relative luminance ($L$), WCAG 2.1 Contrast Ratio ($\text{CR}$), and CIEDE2000 ($\Delta E^*_{00}$) are computed deterministically.
- **FR-10 (Visibility Bifurcation Rules):** A text region qualifies as **Human-Visible** if and only if all of the following hold:
  - `origin_pass == "baseline"`
  - `frame_index == 0`
  - $\text{CR} \ge 3.0$ (configurable via `PIXEL_GUARD_WCAG_MIN`)
  - $\Delta E^*_{00} \ge 15.0$ (configurable via `PIXEL_GUARD_DELTA_E_MIN`)
  - `bbox_height_px >= 8` (configurable via `PIXEL_GUARD_MIN_HEIGHT_PX`)
  - `mean_alpha >= 0.30` (configurable via `PIXEL_GUARD_ALPHA_MIN`)
  - Not isolated in extreme `< 4px` canvas bleed margins with sub-10px height.
  Any region failing one or more criteria is classified as **Hidden / Camouflaged** and assigned specific anomaly flags (`LOW_CONTRAST_CAMOUFLAGE`, `SUB_JND_COLOR_DELTA`, `ALPHA_TRANSPARENCY_CAMOUFLAGE`, `MICRO_TEXT_ANOMALY`, `FREQUENCY_EDGE_CAMOUFLAGE`, `CHROMINANCE_CAMOUFLAGE`, `INACTIVE_FRAME_OBFUSCATION`, `MARGIN_BLEED_PLACEMENT`).

### 4.5 Threat Heuristics and Output Formatting (FR-11 to FR-14)

- **FR-11 (Heuristic Threat Evaluation):** Every extracted pixel text region and metadata field must be scanned for:
  - `INSTRUCTION_OVERRIDE_MATCH`: Directives to ignore, disregard, bypass, or forget prior/previous/above/system instructions.
  - `SYSTEM_ROLE_SPOOFING`: Fake role delimiters (`[SYSTEM]`, `[ASSISTANT]`, `SYSTEM INSTRUCTION:`) or privilege escalation (`developer mode`, `administrative override`, `DAN mode`).
  - `PERSONA_JAILBREAK_MATCH`: Commands to adopt unrestricted or safety-bypassed personas.
  - `PROMPT_EXFILTRATION_REQUEST`: Commands to reveal system prompts, secrets, API keys, or conversation history.
  - `EXTERNAL_URL_EXFILTRATION`: Markdown image beacons (`![...](https://...)`) or URLs carrying exfiltration query parameters.
  - `COMMAND_EXECUTION_SIGNATURE`: Shell/code execution primitives (`curl `, `wget `, `bash -c`, `<script>`, `eval(`, `exec(`, `os.system`, `subprocess.Popen`, `base64 -d`).
  - `OBFUSCATED_PAYLOAD_DETECTED`: Base64, hexadecimal, or URL-encoded tokens (`> 20` characters) decoding to printable ASCII (which are recursively re-evaluated against all regex rules), or unspaced tokens (`> 24` characters) exceeding Shannon entropy `4.7` bits/character.
- **FR-12 (Section 1 vs Section 2 Routing):**
  - **Section 1 (Human-Visible Safe Text):** Contains exclusively regions classified as Human-Visible (FR-10) with threat severity `CLEAN`.
  - **Section 2 (Quarantined and Hidden / Suspicious Text):** Contains all Hidden/Camouflaged pixel regions, all metadata findings containing non-benign or notable payloads (with any metadata containing threat matches escalated to `HIGH`/`CRITICAL` and benign descriptive metadata listed transparently with `METADATA_CONTAINER_PAYLOAD` if suspicious or recorded in provenance), and any Human-Visible text matching a threat signature.
- **FR-13 (JSON Schema Compliance):** Running `--format json` must emit UTF-8 JSON conforming strictly to `assets/report_schema.json`.
- **FR-14 (Automatic Root HTML Dashboard and Live Image Re-Scanning):** Every scan (unless `--no-dashboard` is specified) must automatically generate/update `dashboard.html` at the skill root directory (`<skill_root>/dashboard.html`, rendered from `scripts/pixel_guard/dashboard_ui.py`) and start/update a loopback (`127.0.0.1`) Studio Server exposing `GET /api/browse`, `POST /api/scan-upload`, `POST /api/scan-path`, `GET /api/fixtures`, and `GET /events` SSE streaming. Clicking **Load Image** must open an interactive file chooser (defaulting to `tests/images/` with directory navigation plus native OS file selection) so users can re-run `pixel-guard` on new images and refresh all visual panes in place.

---

## 5. Non-Functional Requirements

- **NFR-01 (Latency):** End-to-end analysis of a standard `1920x1080` image on a 4-core x86_64 or ARM64 CPU (no GPU) must complete in under `2.5 seconds`.
- **NFR-02 (Memory Ceiling):** Peak Resident Set Size (RSS) / Python heap overhead during single-image execution must remain below `512 MB`.
- **NFR-03 (Air-Gapped Security and Privacy):** `pixel-guard` must perform zero outbound network requests during image scanning. No pixels, hashes, filenames, or OCR strings may leave the local host.
- **NFR-04 (HCLS Data Governance):** All repository fixtures, sample prompts, documentation examples, and test cases must be 100% synthetic and contain zero Protected Health Information (PHI) or Personally Identifiable Information (PII) under HIPAA Safe Harbor rules.
- **NFR-05 (Cross-Platform Portability):** All Python modules must run on Linux, macOS, and Windows under Python `3.10+` using relative paths and environment-driven configuration (`PIXEL_GUARD_*`).
- **NFR-06 (Extensibility):** Adding new heuristic signatures or vision passes must require only declarative entries in `heuristics.py` or `preprocessor.py` without breaking the `ScanReport` schema.

---

## 6. Error Handling and Edge Cases

| Case ID | Input / Runtime Condition | Detection Mechanism | System Behavior | CLI Exit Code |
| :--- | :--- | :--- | :--- | :--- |
| **EC-01** | Missing file path or directory passed instead of file | `Path.is_file()` pre-check in `validator.py` | Emit structured error message to `stderr` (or JSON error object in `--format json`); abort pipeline cleanly without traceback. | `2` |
| **EC-02** | Zero-byte file or truncated raster stream | File size check + `PIL.Image.verify()` / `Image.load()` exception trap | Reject file before CV buffer allocation; report `CORRUPTED_IMAGE_STREAM`. | `2` |
| **EC-03** | Extension spoofing or polyglot file (for example, HTML/JS saved as `.png`) | Raw magic-byte comparison + 4 KB header/trailer script signature scan | Reject immediately; report `POLYGLOT_OR_INVALID_SIGNATURE`. | `2` |
| **EC-04** | Unsupported file format (for example, `.pdf`, `.svg`, `.mp4`, `.exe`) | Magic-byte whitelist check | Reject with descriptive `UNSUPPORTED_IMAGE_FORMAT` message listing supported raster formats. | `2` |
| **EC-05** | Decompression bomb (for example, `20000x20000` PNG exceeding `36MP` ceiling) | `PIL.Image.MAX_IMAGE_PIXELS` + explicit `width * height > config.max_image_pixels` guard | Abort decoding prior to `numpy` array materialization; report `IMAGE_DIMENSIONS_EXCEEDED`. | `2` |
| **EC-06** | Valid solid-color or photographic image containing zero text and zero metadata | OCR returns 0 tokens across all active passes; metadata dictionary empty | Return `Scan Status: PASSED`, `Total Text Regions Found: 0`, Section 1 `[No visible text detected]`, Section 2 `[No suspicious text detected]`. | `0` |
| **EC-07** | Excessive animation frames (for example, 250-frame GIF) | Frame loop counter vs `config.max_frames` + perceptual frame-diff filter | Deduplicate static frames and cap analysis at `PIXEL_GUARD_MAX_FRAMES` distinct frames; record truncation notice in report metadata. | `0` (or `1`/`3` if `--fail-on-findings` and threats found) |
| **EC-08** | Malformed or non-UTF8 binary bytes inside EXIF `UserComment` or `MakerNote` | Safe byte-decoding cascade (`utf-8`, `utf-16-be/le`, `latin-1` fallback) + printable ASCII filter | Strip null/control bytes without raising `UnicodeDecodeError`; analyze surviving printable strings. | `0` (or `1`/`3` if `--fail-on-findings` and threats found) |
| **EC-09** | Local `tesseract` binary missing from `PATH` and `PIXEL_GUARD_TESSERACT_CMD` unset | `shutil.which()` check in `ocr_engine.py` | Attempt configured `easyocr` fallback if installed; otherwise raise `OCREngineUnavailableError` with installation remediation instructions. | `2` |
| **EC-10** | Unwritable output report or dashboard file path (permission denied) | `OSError` / `PermissionError` catch around output writer | Print clear filesystem error to `stderr` while preserving stdout report integrity if applicable. | `2` |
| **EC-11** | `--fail-on-findings` enabled when hidden text (`WARNING`) or prompt injection (`CRITICAL`) is found | Post-scan status evaluation in `pixel_guard_cli.py` | Output complete Dual-Section report, then return `1` for `WARNING` or `3` for `CRITICAL INJECTION DETECTED` (returns `0` by default when `--fail-on-findings` is omitted so agent tool calls receive the full report text). | `1` or `3` |
