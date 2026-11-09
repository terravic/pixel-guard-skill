# Threat Taxonomy and Heuristic Detection Rules

This reference documents the Visual Indirect Prompt Injection (V-IPI) attack vectors and deterministic text-level signatures enforced by `pixel-guard`.

---

## 1. Visual and Container Attack Vector Taxonomy

| Vector ID | Attack Category | Camouflage Mechanism | Vision / Ingestion Countermeasure | Anomaly Flag |
| :--- | :--- | :--- | :--- | :--- |
| **V-01** | Low-Contrast / Invisible Ink | Foreground RGB differs from local background by fewer than 5 intensity levels (for example, `#FAFAFA` on `#FFFFFF`). | Pass B (`clahe_contrast`): $35 \times 35$ local median background subtraction with $25 \times 25$ local peak-envelope anti-aliased normalization. | `LOW_CONTRAST_CAMOUFLAGE`, `SUB_JND_COLOR_DELTA` |
| **V-02** | Alpha-Channel Opacity Masking | Text drawn with near-zero alpha (`1%` to `10%`) or raw RGB text buried beneath `alpha = 0` pixels. | Pass D (`alpha_isolation`): Partial-alpha deviation binarization plus raw uncomposited RGB extraction where `alpha < 77`. | `ALPHA_TRANSPARENCY_CAMOUFLAGE` |
| **V-03** | Micro-Typography | Glyphs rendered at `2px` to `7px` height inside whitespace or margin regions. | Pass F (`micro_upscale`): Connected-component ROI selection and $4\times$ bicubic (`INTER_CUBIC`) super-resolution. | `MICRO_TEXT_ANOMALY` |
| **V-04** | Metadata / Container Smuggling | Adversarial strings stored in EXIF (`UserComment`, `ImageDescription`, `Artist`, `XPComment`), PNG `tEXt`/`zTXt`/`iTXt` chunks, XMP XML, IPTC, or GIF comments. | Stage 1 (`metadata.py`): Multi-format container parser forwarding sanitized strings directly to Stage 5 heuristics. | `METADATA_CONTAINER_PAYLOAD` |
| **V-05** | Spatial-Frequency / Embossed Gradients | Dual-edge luminance bevels (`#848484` / `#7C7C7C` on `#808080`) that cancel out under global thresholding. | Pass E (`edge_frequency`): Sobel and Laplacian gradient magnitude with morphological closing and inversion. | `FREQUENCY_EDGE_CAMOUFLAGE` |
| **V-06** | Iso-Luminant Chrominance Camouflage | Foreground and background share near-identical CIE luminance ($L^*$) while varying subtly in `a*` or `b*` hue channels. | Pass C (`perceptual_channels`): Independent percentile stretching on CIE $L^*a^*b^*$ `a*`, `b*` and HSV `S` planes. | `CHROMINANCE_CAMOUFLAGE` |
| **V-07** | Multi-Frame Flash Obfuscation | Prompt overrides placed on short-duration animation frames or secondary TIFF pages (`frame_index > 0`). | Stage 2 (`preprocessor.py`): Perceptual pixel-delta frame iterator tagging all secondary frames. | `INACTIVE_FRAME_OBFUSCATION` |
| **V-08** | Margin Bleed Placement | Micro-instructions positioned within `4px` of outer image boundaries where UI previews crop or shadow edges. | Stage 4 (`color_science.py`): Spatial boundary proximity check combined with glyph height profiling. | `MARGIN_BLEED_PLACEMENT` |

---

## 2. Semantic Heuristic Rule Categories

Every string extracted from pixel OCR or container metadata is evaluated against deterministic regular-expression and information-theoretic rules:

| Rule ID | Security Flag | Default Severity | Pattern Target |
| :--- | :--- | :--- | :--- |
| **HR-01** | `INSTRUCTION_OVERRIDE_MATCH` | `CRITICAL` | Directives instructing an agent to ignore, disregard, bypass, override, or forget previous, prior, above, or system instructions. |
| **HR-02** | `SYSTEM_ROLE_SPOOFING` | `CRITICAL` | Synthetic message headers (`[SYSTEM]`, `[ASSISTANT]`, `SYSTEM INSTRUCTION:`) or privilege switches (`developer mode`, `administrative override`, `DAN mode`, `root access`). |
| **HR-03** | `PERSONA_JAILBREAK_MATCH` | `HIGH` | Imperatives commanding the model to act as an unrestricted, unfiltered, or safety-exempt entity, or to bypass safety checks. |
| **HR-04** | `PROMPT_EXFILTRATION_REQUEST` | `CRITICAL` | Commands to output, print, reveal, forward, or exfiltrate system prompts, API keys, credentials, secrets, or chat transcripts. |
| **HR-05** | `EXTERNAL_URL_EXFILTRATION` | `CRITICAL` | Markdown image beacons (`![alt](https://...)`) or URLs embedding query-string exfiltration sinks (`?token=`, `?data=`, `?secret=`, `/leak`, `/sink`, `/exfil`). |
| **HR-06** | `COMMAND_EXECUTION_SIGNATURE` | `CRITICAL` | Shell or script execution primitives (`curl `, `wget `, `bash -c`, `sh -c`, `<script>`, `eval(`, `exec(`, `os.system(`, `subprocess.Popen`, `base64 -d`). |
| **HR-07** | `OBFUSCATED_PAYLOAD_DETECTED` | `HIGH` (escalates to `CRITICAL` if decoded text matches `HR-01..HR-06`) | Base64, hexadecimal, or percent-encoded substrings (`>= 20` characters) decoding to printable ASCII, or unspaced non-URL tokens (`>= 24` characters) with Shannon entropy `> 4.7` bits/character. |

---

## 3. Shannon Entropy Calculation

For candidate unspaced tokens $s$ of length $N \ge 24$, Shannon entropy $H(s)$ in bits per character is computed as:

$$H(s) = -\sum_{c \in \Sigma} p(c) \log_2 p(c), \quad p(c) = \frac{\text{count}(c, s)}{N}$$

Standard English words and clinical nomenclature exhibit $H(s) \in [2.8, 4.2]$, whereas compressed, encrypted, or Base64-encoded command payloads typically exhibit $H(s) > 4.7$.
