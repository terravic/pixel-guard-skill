# Product Requirements Document: pixel-guard

**Identifier:** `pixel-guard`  
**Version:** 1.0.0  
**Status:** Specification v1.0  
**Classification:** Deterministic Multimodal Pre-Flight Security Skill  
**License:** Apache-2.0

---

## 1. Overview and Problem Statement

AI agent harnesses accept multimodal inputs, allowing users and automated workflows to reference screenshots, scanned forms, supplier invoices, and technical diagrams alongside text prompts. Passing untrusted raster images directly into Multimodal Large Language Models (MLLMs) exposes the agent runtime to Visual Indirect Prompt Injections (V-IPI) and container-level instruction smuggling.

Adversaries embed directives that remain imperceptible during human visual review yet survive vision-encoder normalization, contrast stretching, alpha flattening, or metadata ingestion. Vectors include sub-threshold foreground-to-background contrast (for example, `#FAFAFA` glyphs on a `#FFFFFF` background), near-zero or zero-alpha channel layers, micro-typography (`2px` to `7px` height), non-pixel metadata payloads (`EXIF`, `XMP`, `IPTC`, PNG text chunks, GIF comments), secondary animation frames, embossed spatial-frequency watermarks, border margin-bleed placement, and visible prompt-override syntax containing Markdown exfiltration URLs or encoded command payloads.

`pixel-guard` mitigates these vectors through an air-gapped, deterministic pre-flight analysis pipeline written in Python. The skill uses classical computer vision, local Optical Character Recognition (OCR), mathematical color science (WCAG 2.1 relative luminance contrast and CIEDE2000 perceptual color difference), and rule-based threat heuristics. No local or remote LLM is invoked at any stage of image inspection. Every analyzed asset produces a two-section report separating human-verified visible text (Section 1) from quarantined, camouflaged, or adversarial findings (Section 2), alongside schema-validated JSON serialization and a self-contained root `dashboard.html` inspection view.

---

## 2. User Stories and Scope

### 2.1 Target Personas and User Stories

| Persona ID | Target Audience | User Story | Acceptance Outcome |
| :--- | :--- | :--- | :--- |
| **US-01** | Non-Technical Operations Analyst | As an analyst reviewing scanned vendor invoices, multi-page logs, or support attachments in an agent chat session, I want to pass a relative file path so the skill screens the image for hidden instructions before reading it. | Agent executes `pixel-guard` on the file path first, consumes only Section 1 verified text, and reports any Section 2 quarantine alerts in plain language. |
| **US-02** | Agent Platform Security Engineer | As a security engineer configuring multimodal agent harnesses, I want a deterministic `PreToolUse` hook (`scripts/pre_tool_hook.py`) and MCP server (`inspect_image_security`) that gate direct MLLM ingestion of unscreened image bytes. | Direct image-read tool calls are intercepted until `pixel-guard` completes with deterministic exit codes and schema-validated output. |
| **US-03** | Data Governance and Privacy Reviewer | As a governance reviewer, I require that pre-flight document screening runs 100% locally with zero external API calls, zero outbound network requests, and project-relative path reporting so local data residency is preserved. | Zero outbound network sockets are opened; processing stays within local CPU/RAM budgets and emits project-relative file paths. |
| **US-04** | Security Operations Reviewer | As an analyst inspecting single-page or multi-page images, I want a standalone `dashboard.html` at the project root displaying the inspected image with aligned bounding boxes, page navigation controls, an Enhanced Reveal toggle, pending/blocked scan state feedback, and a `Load Image` file dialog for live local re-scanning. | Every scan writes `dashboard.html` at the project root and connects to the local loopback server (`127.0.0.1:18765`) for live re-scanning. |

### 2.2 In-Scope Capabilities

1. **Supported Raster Formats:** JPEG (`.jpg`, `.jpeg`), PNG (`.png`, including RGBA and APNG), WebP (`.webp`), BMP (`.bmp`), GIF (`.gif`, static and multi-frame), TIFF (`.tif`, `.tiff`, single-page and multi-page documents), and Netpbm (`.pbm`, `.pgm`, `.ppm`).
2. **Binary Signature and Polyglot Validation:** Magic-byte verification, script/shebang/HTML/ELF/PE polyglot header and trailer rejection, mid-stream truncation checks, and pixel-count decompression bomb protection.
3. **Container Metadata Harvesting:** Extraction and sanitization of EXIF IFDs (`0th`, `Exif`, `1st`, `GPS`, `Interop`), PNG textual chunks (`tEXt`, `zTXt`, `iTXt`), XMP XML packets, IPTC descriptors, and GIF comment extensions.
4. **Six-Pass Deterministic Computer Vision Decomposition with ROI Cropping and Resolution Scaling:**
   - Oversized full-frame inputs (`max(width, height) > PIXEL_GUARD_MAX_OCR_DIM`, default `1600`) are downscaled proportionally for full-frame passes while remapping all OCR bounding boxes back to native `1x` coordinates.
   - High-contrast visible strokes (`work_dev >= 40`) are dilated into exclusion masks (`vis_stroke_mask`, `vis_edge_mask`) so JPEG DCT ringing halos around normal text do not trigger redundant anomaly passes.
   - Pass A (`baseline`): White-composited RGB grayscale baseline (inverting dark-mode backgrounds when median luminance `< 96`).
   - Pass B (`clahe_contrast`): $35 \times 35$ local median background subtraction with $25 \times 25$ local peak-envelope normalization and connected-component ROI cropping.
   - Pass C (`perceptual_chroma`): Local median deviation across CIE $L^*a^*b^*$ chrominance (`a*`, `b*`) and HSV saturation (`S`) channels with ROI cropping to expose iso-luminant hue camouflage.
   - Pass D (`alpha_partial` / `alpha_zero_rgb`): Partial-alpha deviation isolation ($0 < \alpha < 255$) plus raw uncomposited RGB extraction under low-alpha masks ($\alpha < 0.30$).
   - Pass E (`edge_frequency`): Sobel gradient magnitude enhancement with morphological closing and ROI cropping to expose embossed or outline-only residual glyphs.
   - Pass F (`micro_upscale`): Native `1x` connected-component micro-glyph ROI selection upscaled $4\times$ via bicubic interpolation (`INTER_CUBIC`) to recover `2px` to `7px` text.
5. **Multi-Page Document and Multi-Frame Container Handling:** Multi-page `TIFF` files treat every page (`0 .. PIXEL_GUARD_MAX_FRAMES - 1`) as an independent document page eligible for Section 1 without secondary-frame penalties. Animated containers (`GIF`, `WebP`, `APNG`) deduplicate identical holds via perceptual grayscale delta and tag secondary-frame text (`frame_index > 0`) with `INACTIVE_FRAME_OBFUSCATION`.
6. **Air-Gapped Local OCR and Spatial Deduplication:** Concurrent local Tesseract execution with bounded OpenMP thread limits, configurable per-invocation timeouts (`PIXEL_GUARD_OCR_TIMEOUT_S`), PSM 11 short-circuiting when PSM 6 recovers structured lines, and per-page spatial Intersection-over-Union (IoU) and baseline-containment deduplication.
7. **Mathematical Visibility Profiling:** Polarity-aware foreground stroke and 3-pixel dilated background collar sampling, WCAG 2.1 contrast ratio computation, and CIEDE2000 ($\Delta E^*_{00}$) color-difference scoring.
8. **Deterministic Threat Heuristic Engine:** Compiled regular-expression catalog for instruction overrides, system role spoofing, persona jailbreaks, Markdown image exfiltration, shell/script injection, space-tolerant Base64/Hex/URL payload decoding, and Shannon entropy anomaly scoring.
9. **Multi-Format Reporting, Root Dashboard, and Harness Integrations:** Dual-Section Markdown report, JSON Schema validated report (`assets/report_schema.json`), root `dashboard.html` with live `Load Image` execution (`POST /api/scan-upload`), multi-page navigation, pending/blocked scan state transitions, SSE streaming, CLI script, stdio MCP server, and `PreToolUse` lifecycle hook.

### 2.3 Out-of-Scope Boundaries

1. **Zero LLM Usage:** Neither cloud nor local generative language/vision models are called to transcribe, classify, or summarize images.
2. **Destructive Image Inpainting:** `pixel-guard` extracts, classifies, and quarantines text; it does not overwrite or modify source image files.
3. **Cryptographic Steganalysis:** Breaking encrypted LSB bitstreams lacking visual glyph structure or container text is outside scope because vision encoders do not decrypt cryptographic bitstreams.
4. **Audio/Video Stream Decoding:** Container video formats (`.mp4`, `.mkv`, `.avi`) and audio files are outside scope.

---

## 3. Technical Architecture

### 3.1 Harness Integration Sequence Diagram

```text
+---------------+      +-----------------------+      +-------------------------+      +--------------------+
|     User      |      |     Agent Harness     |      |  pixel-guard Pre-Flight |      |   Downstream LLM   |
|               |      | (Skill / Hook / MCP)  |      |  (Deterministic Python) |      |   (Text Context)   |
+-------+-------+      +-----------+-----------+      +------------+------------+      +---------+----------+
        |                          |                               |                             |
        | 1. Pass relative path    |                               |                             |
        |------------------------->|                               |                             |
        |                          | 2. PreToolUse Hook / SKILL.md |                             |
        |                          |    gates raw image read       |                             |
        |                          |------------------------------>|                             |
        |                          |                               | 3. Magic-byte & polyglot    |
        |                          |                               |    validation               |
        |                          |                               | 4. Harvest EXIF/PNG/XMP     |
        |                          |                               | 5. Generate CV Passes A-F   |
        |                          |                               |    + multi-page/frame split |
        |                          |                               | 6. Parallel local Tesseract |
        |                          |                               | 7. WCAG CR & CIEDE2000 math |
        |                          |                               | 8. Regex, Base64 & entropy  |
        |                          |                               | 9. Update dashboard.html    |
        |                          |                               |                             |
        |                          | 10. Dual-Section Report       |                             |
        |                          |     (Sec 1 Safe / Sec 2 Quar) |                             |
        |                          |<------------------------------|                             |
        |                          |                               |                             |
        |                          | 11. If CRITICAL/WARNING:      |                             |
        | 12. Quarantine alert &   |     Isolate Sec 2; forward    |                             |
        |     safe workflow output |     ONLY Sec 1 verified text  |                             |
        |<-------------------------|------------------------------------------------------------>|
```

### 3.2 Six-Stage Internal Processing Flow

```text
[Input Image Relative Path]
        |
        v
+-----------------------------------------------------------------------+
| STAGE 1: INGESTION, MAGIC-BYTE VALIDATION & METADATA HARVESTING       |
|  - Verify header signature (JPEG/PNG/WEBP/BMP/GIF/TIFF/PNM)           |
|  - Block HTML/JS/shebang/ELF/PE polyglots & decompression bombs       |
|  - Extract EXIF IFDs, PNG tEXt/zTXt/iTXt, XMP XML, IPTC, GIF comments |
+-----------------------------------+-----------------------------------+
                                    |
                 +------------------+------------------+
                 |                                     |
                 v                                     |
+-----------------------------------+                  |
| STAGE 2: MULTI-PAGE & CV PASSES   |                  |
|  - Preserve TIFF pages / diff GIF |                  |
|  - Mask high-contrast DCT halos   |                  |
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
|  - Bounded OpenMP Tesseract TSV   |                  |
|  - 1x native bbox remapping       |                  |
|  - Per-page IoU deduplication     |                  |
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
| STAGE 6: BIFURCATED OUTPUT & ROOT DASHBOARD GENERATION                |
|  - Section 1: Human-Visible & Threat-Clean Text                       |
|  - Section 2: Quarantined / Hidden / Suspicious Findings              |
|  - Outputs: Markdown, Schema-Validated JSON, root dashboard.html      |
+-----------------------------------------------------------------------+
```

### 3.3 Component Responsibilities

- `SKILL.md`: Agent harness manifest defining pre-flight invocation rules, Section 1 consumption boundaries, and Section 2 quarantine handling.
- `dashboard.html`: Root interactive HTML5 inspection UI written and updated on each scan.
- `scripts/pixel_guard_cli.py`: Command-line entry script delegating to `pixel_guard.cli_entry:main`.
- `scripts/mcp_server.py`: Stdio Model Context Protocol server exposing `inspect_image_security` with a built-in JSON-RPC 2.0 fallback.
- `scripts/pre_tool_hook.py`: Lifecycle `PreToolUse` gate reading hook payloads on `stdin` and intercepting unscreened image reads across `view_file`, `read_file`, `Read`, and `open_file`.
- `scripts/pixel_guard/`: Core Python package (`config.py`, `models.py`, `validator.py`, `metadata.py`, `preprocessor.py`, `ocr_engine.py`, `color_science.py`, `heuristics.py`, `formatter.py`, `pipeline.py`, `cli_entry.py`, `dashboard.py`, `dashboard_ui.py`).
- `assets/`: JSON schema (`report_schema.json`), harness configuration templates (`mcp_config.json`, `hooks.json`, `plugin.json`), and architecture overview diagram (`pixel_guard_overview.png`).
- `references/`: Technical reference documents covering color science formulas, dashboard design tokens, harness integrations, and threat taxonomy.
- `tests/`: Multi-instance synthetic generator (`generate_test_images.py`), 37 persisted sample images plus `manifest.json` (`tests/images/`), and automated smoke, unit, and end-to-end test suites.

---

## 4. Functional Requirements

### 4.1 Input Ingestion and Structural Validation (FR-01 to FR-03)

- **FR-01 (Magic-Byte Verification):** The validator inspects raw leading file bytes to confirm signatures for JPEG (`FF D8 FF`), PNG (`89 50 4E 47 0D 0A 1A 0A`), GIF (`47 49 46 38`), BMP (`42 4D`), WebP (`52 49 46 46 ... 57 45 42 50`), TIFF (`49 49 2A 00` or `4D 4D 00 2A`), and Netpbm (`P1` through `P6`). Unrecognized signatures raise `ValidationError` and return exit code `2`.
- **FR-02 (Polyglot Rejection):** The validator inspects the leading 4 KB and trailing 4 KB of the file for embedded script or executable markers (`<!DOCTYPE`, `<html`, `<script`, `<?php`, leading `#!` shebangs, ELF `\x7fELF`, PE `MZ` outside BMP context) and rejects polyglot streams with exit code `2`.
- **FR-03 (Decompression Bomb and Truncation Guard):** Images exceeding `PIXEL_GUARD_MAX_PIXELS` (default `36,000,000` pixels) or corrupted raster streams failing `Image.verify()` / `Image.load()` are rejected prior to full buffer allocation with exit code `2`.

### 4.2 Container Metadata and Multi-Frame Extraction (FR-04 to FR-05)

- **FR-04 (Metadata Harvesting):** Non-empty textual values in EXIF IFDs (`ImageDescription`, `UserComment`, `Artist`, `Copyright`, `Software`, `XPTitle`, `XPComment`, `XPAuthor`, `XPKeywords`, `XPSubject`, `DocumentName`, `PageName`, `HostComputer`, `MakerNote`), PNG chunks (`tEXt`, `zTXt`, `iTXt`), XMP XML packets, IPTC records, and GIF comment blocks are extracted, sanitized, labeled with provenance (`EXIF:<Tag>`, `PNG:<Chunk>:<Key>`, `XMP:Packet`, `GIF:comment`), and evaluated by Stage 5 threat rules.
- **FR-05 (Multi-Page and Multi-Frame Decomposition):** For multi-page `TIFF` documents, every page up to `PIXEL_GUARD_MAX_FRAMES` (default `24`) is extracted with `is_document_page=True` and evaluated independently without animation-frame skipping or secondary-frame penalties. For animated containers (`GIF`, `WebP`, `APNG`), consecutive frames whose mean grayscale delta is below `1.0` and max pixel delta `< 3` are deduplicated, and text discovered on `frame_index > 0` is tagged with `INACTIVE_FRAME_OBFUSCATION`.

### 4.3 Computer Vision Multi-Pass and Local OCR (FR-06 to FR-08)

- **FR-06 (Deterministic Vision Passes and ROI Cropping):** Full-frame inputs exceeding `PIXEL_GUARD_MAX_OCR_DIM` (`1600px` default) are downscaled for Passes A through E while Pass F operates at native `1x` resolution. High-contrast strokes (`work_dev >= 40`) are masked out of Passes B, C, and E so compression halos around normal text are ignored, and surviving subtle anomalies are cropped into tight connected-component ROIs (`_build_anomaly_pass_images`):
  1. `baseline`: RGBA composited over opaque `#FFFFFF`, converted to `uint8` grayscale (inverted when median luminance `< 96` for dark backgrounds).
  2. `clahe_contrast`: $35 \times 35$ local median background subtraction (`|gray - medianBlur(gray, 35)|`) normalized against a $25 \times 25$ dilated local peak envelope.
  3. `perceptual_chroma`: CIE $L^*a^*b^*$ `a*` and `b*` channels and HSV `S` channel normalized via local median deviation when cross-channel RGB difference `>= 3`.
  4. `alpha_partial` / `alpha_zero_rgb`: Partial-alpha deviation isolation ($0 < \alpha < 255$) and uncomposited raw RGB grayscale masked to pixels where $\alpha < 77$ (`30%` opacity).
  5. `edge_frequency`: Combined Sobel gradient magnitude, despeckling, $3 \times 3$ morphological closing, and inversion to dark strokes on white background.
  6. `micro_upscale`: Candidate micro-glyph connected-component clusters (`2px` to `9px` height) on native `1x` pixels locally normalized and upscaled $4\times$ via `INTER_CUBIC`.
- **FR-07 (Air-Gapped Parallel OCR):** Active passes execute concurrently via local Tesseract (`--oem 3` LSTM) with bounded OpenMP thread counts (`OMP_THREAD_LIMIT`) and per-invocation timeouts (`PIXEL_GUARD_OCR_TIMEOUT_S`, default `10.0s`). When primary `PSM 6` recovers structured text lines, redundant `PSM 11` sparse retries are skipped. Word-level bounding boxes `(x, y, w, h)` are mapped back to native `1x` page/frame coordinates.
- **FR-08 (Cross-Pass Line Consolidation and Per-Page Deduplication):** Horizontally adjacent words on the same baseline are merged into phrase bounding boxes. Detections on the same `frame_index` sharing spatial IoU `>= 0.55`, baseline `>= 65%` containment, or vertical overlap `>= 0.55` and horizontal overlap `>= 0.50` with normalized token similarity `>= 0.72` are deduplicated, preserving `baseline` as `origin_pass` whenever the text was already legible in Pass A.

### 4.4 Color Science and Visibility Classification (FR-09 to FR-10)

- **FR-09 (Foreground and Local Collar Profiling):** Within each region's native RGBA crop, glyph strokes ($M_{fg}$) are segmented via polarity-oriented thresholding anchored against outer border pixels. Foreground color ($C_{fg}$) is the median RGB of $M_{fg}$; local background color ($C_{bg}$) is the median RGB of the 3-pixel morphologically dilated collar ($M_{dilated} \setminus M_{fg}$). Relative luminance ($L$), WCAG 2.1 Contrast Ratio ($\text{CR}$), and CIEDE2000 ($\Delta E^*_{00}$) are computed deterministically with LRU caching.
- **FR-10 (Visibility Bifurcation Rules):** A text region qualifies as **Human-Visible** if and only if all of the following hold:
  - `origin_pass == "baseline"`
  - `frame_index == 0` or `is_document_page == True` (all pages of a multi-page `TIFF` document)
  - $\text{CR} \ge 3.0$ (configurable via `PIXEL_GUARD_WCAG_MIN`)
  - $\Delta E^*_{00} \ge 15.0$ (configurable via `PIXEL_GUARD_DELTA_E_MIN`)
  - `bbox_height_px >= 8` (configurable via `PIXEL_GUARD_MIN_HEIGHT_PX`)
  - `mean_alpha >= 0.30` (configurable via `PIXEL_GUARD_ALPHA_MIN`)
  - Not flush within `<= 6px` of outer image borders with compact height `<= 14px`.
  Any region failing one or more criteria is classified as **Hidden / Camouflaged** and assigned anomaly flags (`LOW_CONTRAST_CAMOUFLAGE`, `SUB_JND_COLOR_DELTA`, `ALPHA_TRANSPARENCY_CAMOUFLAGE`, `MICRO_TEXT_ANOMALY`, `FREQUENCY_EDGE_CAMOUFLAGE`, `CHROMINANCE_CAMOUFLAGE`, `INACTIVE_FRAME_OBFUSCATION`, `MARGIN_BLEED_PLACEMENT`).

### 4.5 Threat Heuristics, Relative Paths, and Root Dashboard UI (FR-11 to FR-15)

- **FR-11 (Heuristic Threat Evaluation):** Every extracted pixel text region and metadata field is evaluated for:
  - `INSTRUCTION_OVERRIDE_MATCH`: Directives to ignore, disregard, bypass, override, or forget prior/previous/above/system instructions.
  - `SYSTEM_ROLE_SPOOFING`: Synthetic role delimiters (`[SYSTEM]`, `[ASSISTANT]`, `SYSTEM INSTRUCTION:`) or privilege switches (`developer mode`, `administrative override`, `DAN mode`, `root access`).
  - `PERSONA_JAILBREAK_MATCH`: Commands to adopt unrestricted or safety-exempt personas.
  - `PROMPT_EXFILTRATION_REQUEST`: Commands to reveal system prompts, secrets, API keys, credentials, system memory, or conversation history.
  - `EXTERNAL_URL_EXFILTRATION`: Markdown image beacons (`![...](https://...)`) or URLs carrying exfiltration paths or query parameters.
  - `COMMAND_EXECUTION_SIGNATURE`: Shell/code execution primitives (`curl `, `wget `, `bash -c`, `sh -c`, `<script>`, `eval(`, `exec(`, `os.system`, `subprocess.Popen`, `base64 -d`).
  - `OBFUSCATED_PAYLOAD_DETECTED`: Base64, whitespace-tolerant hexadecimal, or URL-encoded tokens (`>= 20` characters) decoding to printable ASCII (recursively re-evaluated against all regex rules), or unspaced tokens (`>= 24` characters) exceeding Shannon entropy `4.7` bits/character.
- **FR-12 (Section 1 vs Section 2 Routing):**
  - **Section 1 (Human-Visible Safe Text):** Contains exclusively regions classified as Human-Visible (FR-10) with threat severity `CLEAN` (prefixed with `[Page N]` on multi-page `TIFF` documents).
  - **Section 2 (Quarantined and Hidden / Suspicious Text):** Contains all Hidden/Camouflaged pixel regions, suspicious or threat-matching container metadata, and any Human-Visible text matching a threat signature.
- **FR-13 (JSON Schema and Relative Path Standardization):** Running `--format json` emits UTF-8 JSON conforming to `assets/report_schema.json`, with `image_path` normalized to a project-relative path (`to_project_relative_path`).
- **FR-14 (Root `Pixel Guard` Dashboard and Live `Load Image` Studio):** Every scan (unless `--no-dashboard` is specified) generates/updates `dashboard.html` at the project root directory and starts or updates a loopback Studio server (`127.0.0.1:18765`, auto-scanning `18765..18784` if busy). The `Pixel Guard` UI renders per-page Original and Enhanced Reveal previews (`preview_images.frames`) with aligned Section 1 / Section 2 bounding boxes, `<` and `>` page navigation controls and row-click page jumping for multi-page documents, segmented text theme buttons (`Light`, `Dark`, `System`), immediate pending scan (`SCANNING...`, `Processing Image` status pane) and validation-blocked (`BLOCKED`) UI transitions, and a single **Load Image** button posting raw image bytes to `POST /api/scan-upload`.
- **FR-15 (Multi-Instance Synthetic Test Suite):** `tests/generate_test_images.py` generates 37 persisted synthetic raster images across 10 scenario groups in `tests/images/` alongside `tests/images/manifest.json`.

---

## 5. Non-Functional Requirements

- **NFR-01 (Latency):** End-to-end analysis of a `1920x1080` image on a 4-core CPU (no GPU) completes in under `2.5 seconds`; a noisy `3840x2160` (4K) text-dense slide including dashboard preview generation completes in under `6.0 seconds`.
- **NFR-02 (Memory Ceiling):** Peak Python heap overhead during single-image execution remains below `512 MB`.
- **NFR-03 (Air-Gapped Execution):** `pixel-guard` performs zero external network requests during scanning or dashboard rendering. All styles and scripts in `dashboard.html` are self-contained.
- **NFR-04 (Synthetic Test Data):** All repository test images, sample prompts, and documentation examples use synthetic laboratory, supply, and telemetry text.
- **NFR-05 (Cross-Platform Portability):** All Python modules run on Linux, macOS, and Windows under Python `3.10+` using project-relative paths and `PIXEL_GUARD_*` environment variables.
- **NFR-06 (Extensibility):** Adding new heuristic signatures or vision passes requires only declarative updates in `heuristics.py` or `preprocessor.py` without breaking the `ScanReport` schema.

---

## 6. Error Handling and Edge Cases

| Case ID | Input / Runtime Condition | Detection Mechanism | System Behavior | CLI Exit Code |
| :--- | :--- | :--- | :--- | :--- |
| **EC-01** | Missing file path or directory passed instead of file | `Path.is_file()` pre-check in `validator.py` | Emit structured error message to `stderr` (or JSON error object in `--format json`); abort pipeline cleanly without traceback. | `2` |
| **EC-02** | Zero-byte file or truncated raster stream | File size check + `PIL.Image.verify()` / `Image.load()` exception trap | Reject file before CV buffer allocation; report `CORRUPTED_IMAGE_STREAM`. | `2` |
| **EC-03** | Extension spoofing or polyglot file (for example, HTML/JS or script saved as `.png`) | Raw magic-byte comparison + 4 KB header/trailer signature scan | Reject immediately; report `POLYGLOT_OR_INVALID_SIGNATURE`. | `2` |
| **EC-04** | Unsupported file format (for example, `.pdf`, `.svg`, `.mp4`, `.exe`) | Magic-byte allowlist check | Reject with descriptive `UNSUPPORTED_IMAGE_FORMAT` message listing supported raster formats. | `2` |
| **EC-05** | Decompression bomb (for example, `20000x20000` PNG exceeding `36MP` ceiling) | `PIL.Image.MAX_IMAGE_PIXELS` + explicit `width * height > config.max_image_pixels` guard | Abort decoding prior to `numpy` array materialization; report `IMAGE_DIMENSIONS_EXCEEDED`. | `2` |
| **EC-06** | Valid solid-color or photographic image containing zero text and zero metadata | OCR returns 0 tokens across all active passes; metadata dictionary empty | Return `Scan Status: PASSED`, `Total Text Regions Found: 0`, Section 1 `[No verified human-visible safe text detected]`, Section 2 `[No suspicious text detected]`. | `0` |
| **EC-07** | Excessive animation frames or pages (for example, 250-frame GIF) | Frame loop counter vs `config.max_frames` + perceptual frame-diff filter | Deduplicate static animation holds and cap analysis at `PIXEL_GUARD_MAX_FRAMES` pages/frames. | `0` (or `1`/`3` if `--fail-on-findings` and threats found) |
| **EC-08** | Malformed or non-UTF8 binary bytes inside EXIF `UserComment` or `MakerNote` | Byte-decoding cascade (`utf-8`, `utf-16-be/le`, `latin-1` fallback) + printable ASCII filter | Strip null/control bytes without raising `UnicodeDecodeError`; analyze surviving printable strings. | `0` (or `1`/`3` if `--fail-on-findings` and threats found) |
| **EC-09** | Local `tesseract` binary missing from `PATH` and `PIXEL_GUARD_TESSERACT_CMD` unset | `shutil.which()` check in `ocr_engine.py` | Attempt configured `easyocr` fallback if installed; otherwise raise `OCREngineUnavailableError` with installation instructions. | `2` |
| **EC-10** | Unwritable output report or dashboard file path (permission denied) | `OSError` / `PermissionError` catch around output writer | Print filesystem error to `stderr` while preserving stdout report integrity if applicable. | `2` |
| **EC-11** | `--fail-on-findings` enabled when hidden text (`WARNING`) or prompt injection (`CRITICAL`) is found | Post-scan status evaluation in `cli_entry.py` | Output complete Dual-Section report, then return `1` for `WARNING` or `3` for `CRITICAL INJECTION DETECTED` (returns `0` by default when `--fail-on-findings` is omitted so agent tool calls receive the full report text). | `1` or `3` |
