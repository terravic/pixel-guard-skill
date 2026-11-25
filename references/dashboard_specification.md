# Interactive HTML Dashboard Specification

Unless `--no-dashboard` is specified, `pixel-guard` generates a self-contained HTML5 inspection view (`dashboard.html`) at the skill root directory (`dashboard.html`) for offline inspection and live local re-scanning.

---

## 1. Typography and Surface Hierarchy

| Dimension | Standard |
| :--- | :--- |
| **Display Headers** | `Instrument Serif` (with `Georgia` / serif fallback) |
| **Interface Prose & Controls** | `DM Sans` (with system sans-serif fallback) |
| **Tabular & Quantitative Values** | `IBM Plex Mono` with `font-variant-numeric: tabular-nums` |
| **Container Surfaces** | Single-level flat grid with solid surface tokens and `1px solid` structural borders (`6px` to `8px` radius) |
| **Theme Controls** | Segmented text buttons (`Light`, `Dark`, `System`) inside `#theme-btn-light`, `#theme-btn-dark`, `#theme-btn-system` |

---

## 2. Theme Modes and Color Tokens

The navigation bar presents a segmented three-mode theme control persisting selection (`light`, `dark`, `system`) in `localStorage`, tracking `window.matchMedia('(prefers-color-scheme: dark)')` changes in real time, and embedding a host `system_theme` fallback (`PIXEL_GUARD_SYSTEM_THEME`, `GTK_THEME`, or `gsettings` desktop color-scheme).

| Token Role | Light Mode Hex | Dark Mode Hex |
| :--- | :--- | :--- |
| **Viewport Background** | `#FAFAF9` | `#0D0E11` |
| **Card & Panel Surface** | `#FFFFFF` | `#16171D` |
| **Border & Axis Gridline** | `#E7E5E4` | `#292A30` |
| **Interactive Control Border (WCAG AA >= 4.0:1)** | `#787774` | `#757785` |
| **Primary Text** | `#1C1917` | `#ECE8E2` |
| **Secondary / Muted Text (WCAG AA >= 6.2:1)** | `#57534E` (`#787774` border/mute token) | `#9A9895` |

---

## 3. Data Visualization & WCAG 2.2 AA Semantic Palette

| Color Role | Base Viz Stroke Hex | WCAG AA Light Text / Badge Fill | WCAG AA Dark Text | Dashboard Usage |
| :--- | :--- | :--- | :--- | :--- |
| **Teal** | `#0D9488` | `#0F766E` (`5.47:1` w/ `#FFFFFF`) | `#2DD4BF` | Primary `Load Image` action button, focus ring, and active toggles |
| **Amber** | `#D97706` | `#B45309` (`5.02:1` w/ `#FFFFFF`) | `#FBBF24` | Intermediate warning thresholds, low-contrast / micro-text anomalies |
| **Indigo** | `#4F46E5` | `#4338CA` (`7.90:1` on `#FFFFFF`) | `#A5B4FC` | Medium-severity anomaly badges |
| **Emerald** | `#059669` | `#047857` (`5.48:1` w/ `#FFFFFF`) | `#34D399` | Verified Section 1 human-visible bounding boxes and `PASSED` states |
| **Rose** | `#E11D48` | `#BE123C` (`6.29:1` w/ `#FFFFFF`) | `#FB7185` | Critical prompt injections, exfiltration signatures, and quarantined boxes |

---

## 4. View Panes and Accessibility Structure

The page enforces semantic landmarks (skip-to-main link, `<header>`, `<nav>`, `<main>`, `<footer>`), single `<h1>` heading hierarchy, visible `:focus-visible` and `:focus-within` outlines, keyboard activation (`Enter`/`Space`) on clickable table rows and bounding boxes, explicit text state markers (`[SAFE]`, `[CLEAN]`, `[WARNING]`, `[CRITICAL]`, `[SELECTED]`, `[ERROR]`), `aria-live="polite"` feedback announcements, and `prefers-reduced-motion` support:

1. **Header & Load Image Control:** Displays the `Pixel Guard` title, a single **Load Image** button (`#load-image-btn` wrapping `#load-image-file-input`) that opens the native file selection dialog, live execution status feedback (`#scan-feedback-banner`), scan status pill, and `Light / Dark / System` theme selector inside `<nav>`.
2. **Scan Summary Strip:** Displays relative file path, file name, format, pixel dimensions, inspected frame count, Section 1 visible count, Section 2 quarantined count, and scan time in milliseconds.
3. **Inspected Image & Bounding Box Overlay:** Renders the loaded image (`#inspected-image-el`) with aligned per-page bounding boxes (`#bbox-overlay-svg`: `#059669` Emerald / `#047857` badge for Section 1 visible lines, `#E11D48` Rose / `#BE123C` badge or `#D97706` Amber / `#B45309` badge with `#1`, `#2` labels for Section 2 quarantined regions), page navigation controls (`#page-prev-btn`, `#page-indicator-label`, `#page-next-btn`), segmented toggles for **Original Image** vs **Enhanced Reveal**, and **Boxes: On / Off**.
4. **Inspection Channels Breakdown:** Reports `[SAFE]`, `[CLEAN]`, `[WARNING]`, and `[CRITICAL]` counts across all 6 deterministic inspection channels.
5. **Dual-Section Tables:** Side-by-side Section 1 safe copy block and Section 2 quarantine table (`IBM Plex Mono`, `tabular-nums`, keyboard and click-linked to bounding boxes).

---

## 5. Single Load Image Control and Loopback Studio API

Every scan writes `dashboard.html` at the skill root directory (`dashboard.html`) with a SHA-256 hash-pinned `<meta http-equiv="Content-Security-Policy">` policy blocking all external origins. Clicking **Load Image** opens the OS file selection dialog so the user can choose any local raster file, posting raw bytes to the local `127.0.0.1` `DashboardSSEServer` (default port `18765`, enforcing loopback `Host` validation, strict loopback `Origin` allowlisting, per-daemon `X-Pixel-Guard-Token` checks for `file://` origins, HTTP security headers, and `Access-Control-Allow-Private-Network: true` on authorized origins):

- `GET /api/health`: Loopback readiness probe returning `{"status": "ok", "skill": "pixel-guard", "port": <port>}`.
- `POST /api/scan-upload`: Accepts raw image bytes selected via **Load Image**, sanitizes `X-Filename`, executes the 6-stage deterministic `scan_image()` pipeline live inside an ephemeral temporary directory, regenerates `Original Image` and `Enhanced Reveal` PNG previews, updates `dashboard.html` on disk, broadcasts `event: scan_update` via SSE (capped at 16 concurrent clients), and returns the live `ScanReport` JSON (or HTTP `400` structured `ValidationError` JSON on polyglot/corrupt inputs).
- `POST /api/scan-path`: Programmatic loopback endpoint accepting schema-validated `{"image_path": "..."}` strictly within the repository root (HTTP `403` on traversal/out-of-root paths), executing `scan_image()`, syncing `dashboard.html`, and broadcasting SSE updates.
- `POST /api/publish-report`: Loopback report sync endpoint validating payloads against `assets/report_schema.json` and restricting `dashboard_path` writes to `.html` files within the repository root (or active target path).
- `GET /api/fixtures` and `GET /api/browse`: Programmatic discovery endpoints listing synthetic test images in `tests/images/` strictly within the repository root using project-relative paths (HTTP `403` on out-of-root `dir` queries).
