# Interactive HTML Dashboard Specification

When invoked with `--dashboard [path]` (and optionally `--sse-port <port>`), `pixel-guard` generates a self-contained HTML5 telemetry view (`dashboard.html`) designed for offline forensic inspection and live Server-Sent Events (SSE) workspace updates.

---

## 1. Typography and Surface Hierarchy

| Dimension | Standard |
| :--- | :--- |
| **Display Headers** | `Instrument Serif` |
| **Interface Prose & Controls** | `DM Sans` |
| **Tabular & Quantitative Values** | `IBM Plex Mono` with `font-variant-numeric: tabular-nums` |
| **Container Surfaces** | Single-level flat bento grid with solid surface tokens and `1px solid` structural borders (`6px` to `8px` radius); no multi-stop background gradients and no nested card-in-card wrappers |
| **Interactive Icons** | Restricted exclusively to the three minimalist SVG vector buttons inside the top theme switcher (`#theme-btn-light`, `#theme-btn-dark`, `#theme-btn-system`) |

---

## 2. Theme Modes and Color Tokens

The navigation bar presents a segmented three-icon theme control persisting selection (`light`, `dark`, `system`) in `localStorage`, tracking `window.matchMedia('(prefers-color-scheme: dark)')` changes in real time, and embedding a host-OS `system_theme` fallback (`gsettings`/`GTK_THEME`/`kdeglobals` on Linux, `AppleInterfaceStyle` on macOS, `AppsUseLightTheme` on Windows).

| Token Role | Light Mode Hex | Dark Mode Hex |
| :--- | :--- | :--- |
| **Viewport Background** | `#FAFAF9` | `#0D0E11` |
| **Card & Panel Surface** | `#FFFFFF` | `#16171D` |
| **Border & Axis Gridline** | `#E7E5E4` | `#292A30` |
| **Primary Text** | `#1C1917` | `#ECE8E2` |
| **Secondary / Muted Text** | `#787774` | `#9A9895` |

---

## 3. Data Visualization Semantic Palette

| Color Role | Hex Code | Dashboard Usage |
| :--- | :--- | :--- |
| **Vibrant Teal** | `#0D9488` | Baseline metrics, active vision pass series, nominal pipeline edges |
| **Energetic Amber** | `#D97706` | Intermediate warning thresholds, low-contrast / micro-text anomalies |
| **Vivid Indigo** | `#4F46E5` | Perceptual color-space comparisons, metadata & multi-frame nodes |
| **Functional Emerald** | `#059669` | Verified Section 1 human-visible regions, `PASSED` gate states |
| **Deep Rose** | `#E11D48` | Critical prompt injections, exfiltration signatures, threshold violations |

---

## 4. Empirical View Panes

1. **Header & Load Image Control:** Displays the `Pixel Guard` title, a single **Load Image** button (`#load-image-btn` wrapping `#load-image-file-input`) that opens the native file selection dialog, live execution status feedback (`#scan-feedback-banner`), scan status pill, and Light/Dark/System theme selector.
2. **Scan Summary Strip:** Displays file name, format, pixel dimensions, inspected frame count, Section 1 visible count, Section 2 quarantined count, and scan time in milliseconds.
3. **Inspected Image & Bounding Box Overlay:** Renders the actual loaded image (`#inspected-image-el`) with aligned SVG bounding boxes (`#bbox-overlay-svg`: `#059669` Emerald for Section 1 visible lines, `#E11D48` Deep Rose / `#D97706` Amber with `#1`, `#2` badges for Section 2 quarantined regions), plus segmented toggles for **Original Image** vs **Enhanced Reveal** (amplifying low-contrast, chrominance, alpha, and secondary frames) and **Boxes: On / Off**.
4. **Inspection Channels Breakdown:** Reports safe/flagged counts across all 6 deterministic inspection channels.
5. **Dual-Section Tables:** Side-by-side Section 1 safe copy block and Section 2 quarantine table (`IBM Plex Mono`, `tabular-nums`, click-linked to bounding boxes).

---

## 5. Single Load Image Control and Loopback Studio API

Every scan automatically emits `dashboard.html` at the skill root directory (`<skill_root>/dashboard.html`). Clicking **Load Image** opens the OS file selection dialog so the user can pick any sample test image from `tests/images/` or any local raster file, posting raw bytes to the local `127.0.0.1` `DashboardSSEServer` (with `Access-Control-Allow-Private-Network: true` so both `file://` browsers and embedded IDE webviews connect cleanly):

- `GET /api/health`: Loopback readiness probe returning `{"status": "ok", "skill": "pixel-guard", "port": <port>}`.
- `POST /api/scan-upload`: Accepts raw image bytes selected via **Load Image**, executes the full 6-stage deterministic `scan_image()` pipeline live inside a temporary sandbox directory, regenerates `Original Image` and `Enhanced Reveal` PNG previews, updates `dashboard.html` on disk, broadcasts `event: scan_update` via SSE, and returns the live `ScanReport` JSON (or HTTP `400` structured `ValidationError` JSON on polyglot/corrupt inputs).
- `POST /api/scan-path`: Programmatic loopback endpoint accepting `{"image_path": "..."}`, executing `scan_image()`, syncing `dashboard.html`, and broadcasting SSE updates.
- `GET /api/fixtures` and `GET /api/browse`: Programmatic discovery endpoints listing synthetic test images in `tests/images/`.

