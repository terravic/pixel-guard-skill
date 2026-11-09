"""Self-contained HTML5/CSS/JS UI template for Pixel Guard's root dashboard.html."""

from __future__ import annotations

DASHBOARD_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Pixel Guard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet" />
  <style>
    :root,
    [data-theme="light"] {
      --bg-viewport: #FAFAF9;
      --bg-surface: #FFFFFF;
      --border-token: #E7E5E4;
      --text-primary: #1C1917;
      --text-secondary: #787774;
      --checker-a: #F3F2F0;
      --checker-b: #E7E5E4;
      --viz-teal: #0D9488;
      --viz-amber: #D97706;
      --viz-indigo: #4F46E5;
      --viz-emerald: #059669;
      --viz-rose: #E11D48;
      --font-ui: "DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-display: "Instrument Serif", Georgia, serif;
      --font-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    }

    [data-theme="dark"] {
      --bg-viewport: #0D0E11;
      --bg-surface: #16171D;
      --border-token: #292A30;
      --text-primary: #ECE8E2;
      --text-secondary: #9A9895;
      --checker-a: #121318;
      --checker-b: #1D1F27;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-viewport);
      color: var(--text-primary);
      font-family: var(--font-ui);
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 24px;
      background-color: var(--bg-surface);
      border-bottom: 1px solid var(--border-token);
      gap: 16px;
      flex-wrap: wrap;
    }

    .topbar-left {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }

    .brand-title {
      font-family: var(--font-display);
      font-size: 28px;
      font-weight: 400;
      letter-spacing: -0.01em;
      color: var(--text-primary);
    }

    .nav-controls {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    /* Single Load Image Button with Direct Native File Input Overlay */
    .load-image-btn-wrapper {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: var(--font-ui);
      font-size: 13px;
      font-weight: 600;
      padding: 7px 16px;
      border-radius: 6px;
      border: 1px solid var(--viz-teal);
      background-color: var(--viz-teal);
      color: #FFFFFF;
      cursor: pointer;
      overflow: hidden;
      user-select: none;
    }

    .load-image-btn-wrapper.is-busy {
      opacity: 0.65;
      pointer-events: none;
    }

    .load-image-btn-wrapper input[type="file"] {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      opacity: 0;
      cursor: pointer;
      font-size: 0;
    }

    .action-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: var(--font-ui);
      font-size: 12px;
      font-weight: 500;
      padding: 5px 12px;
      border-radius: 6px;
      border: 1px solid var(--border-token);
      background-color: var(--bg-viewport);
      color: var(--text-primary);
      cursor: pointer;
      white-space: nowrap;
      user-select: none;
    }

    .action-btn.active-toggle {
      background-color: var(--viz-teal);
      border-color: var(--viz-teal);
      color: #FFFFFF;
    }

    .segmented-group {
      display: inline-flex;
      border: 1px solid var(--border-token);
      border-radius: 6px;
      background-color: var(--bg-viewport);
      overflow: hidden;
    }

    .seg-btn {
      appearance: none;
      background: transparent;
      border: none;
      border-right: 1px solid var(--border-token);
      color: var(--text-secondary);
      font-family: var(--font-ui);
      font-size: 12px;
      font-weight: 500;
      padding: 5px 11px;
      cursor: pointer;
    }

    .seg-btn:last-child {
      border-right: none;
    }

    .seg-btn.active {
      background-color: var(--bg-surface);
      color: var(--text-primary);
      font-weight: 600;
    }

    .feedback-banner {
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .feedback-banner[data-tone="ok"] {
      color: var(--viz-emerald);
    }

    .feedback-banner[data-tone="warn"] {
      color: var(--viz-amber);
    }

    .feedback-banner[data-tone="error"] {
      color: var(--viz-rose);
    }

    .status-pill {
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid var(--border-token);
      background-color: var(--bg-viewport);
      font-variant-numeric: tabular-nums;
    }

    .status-pill[data-status="PASSED"] {
      color: var(--viz-emerald);
      border-color: var(--viz-emerald);
    }

    .status-pill[data-status="WARNING"] {
      color: var(--viz-amber);
      border-color: var(--viz-amber);
    }

    .status-pill[data-status="CRITICAL INJECTION DETECTED"] {
      color: var(--viz-rose);
      border-color: var(--viz-rose);
    }

    .theme-selector {
      display: inline-flex;
      border: 1px solid var(--border-token);
      border-radius: 6px;
      background-color: var(--bg-viewport);
      overflow: hidden;
    }

    .theme-btn {
      appearance: none;
      background: transparent;
      border: none;
      border-right: 1px solid var(--border-token);
      color: var(--text-secondary);
      width: 34px;
      height: 30px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }

    .theme-btn:last-child {
      border-right: none;
    }

    .theme-btn.active {
      background-color: var(--bg-surface);
      color: var(--text-primary);
    }

    .theme-btn svg {
      width: 15px;
      height: 15px;
      stroke: currentColor;
      fill: none;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .bento-workspace {
      max-width: 1480px;
      margin: 0 auto;
      padding: 20px 24px 36px;
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 16px;
    }

    .pane {
      background-color: var(--bg-surface);
      border: 1px solid var(--border-token);
      border-radius: 8px;
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .span-12 { grid-column: span 12; }
    .span-8  { grid-column: span 8; }
    .span-7  { grid-column: span 7; }
    .span-5  { grid-column: span 5; }
    .span-4  { grid-column: span 4; }

    @media (max-width: 1080px) {
      .span-8, .span-7, .span-5, .span-4 {
        grid-column: span 12;
      }
    }

    .pane-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--border-token);
      padding-bottom: 10px;
      gap: 10px;
      flex-wrap: wrap;
    }

    .pane-title {
      font-family: var(--font-display);
      font-size: 21px;
      font-weight: 400;
      color: var(--text-primary);
    }

    .pane-meta {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .telemetry-strip {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
    }

    @media (max-width: 960px) {
      .telemetry-strip {
        grid-template-columns: repeat(2, 1fr);
      }
    }

    .metric-cell {
      border-right: 1px solid var(--border-token);
      padding-right: 12px;
    }

    .metric-cell:last-child {
      border-right: none;
      padding-right: 0;
    }

    .metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-secondary);
    }

    .metric-value {
      font-family: var(--font-mono);
      font-size: 18px;
      font-weight: 600;
      color: var(--text-primary);
      font-variant-numeric: tabular-nums;
      margin-top: 2px;
      word-break: break-all;
    }

    .metric-sub {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-secondary);
      font-variant-numeric: tabular-nums;
      margin-top: 2px;
    }

    /* Inspected Image & Bounding Box Stage */
    .image-viewport {
      width: 100%;
      min-height: 360px;
      max-height: 560px;
      border: 1px solid var(--border-token);
      border-radius: 6px;
      background-color: var(--checker-a);
      background-image:
        linear-gradient(45deg, var(--checker-b) 25%, transparent 25%),
        linear-gradient(-45deg, var(--checker-b) 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, var(--checker-b) 75%),
        linear-gradient(-45deg, transparent 75%, var(--checker-b) 75%);
      background-size: 16px 16px;
      background-position: 0 0, 0 8px, 8px -8px, -8px 0;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: auto;
      padding: 16px;
      position: relative;
    }

    .image-frame-wrapper {
      position: relative;
      display: inline-block;
      line-height: 0;
      box-shadow: 0 0 0 1px var(--border-token);
      max-width: 100%;
    }

    .inspected-img {
      display: block;
      max-width: 100%;
      max-height: 510px;
      width: auto;
      height: auto;
    }

    .bbox-overlay-svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: auto;
    }

    .bbox-group {
      cursor: pointer;
    }

    .bbox-group:hover rect.bbox-stroke {
      stroke-width: 4;
    }

    .metadata-notice-pill {
      position: absolute;
      bottom: 12px;
      left: 12px;
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 6px 10px;
      border-radius: 6px;
      background-color: var(--bg-surface);
      border: 1px solid var(--viz-rose);
      color: var(--viz-rose);
    }

    /* Channel Breakdown List */
    .channel-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .channel-card {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      border: 1px solid var(--border-token);
      border-radius: 6px;
      background-color: var(--bg-viewport);
      gap: 10px;
    }

    .channel-name {
      font-weight: 500;
      font-size: 13px;
      color: var(--text-primary);
    }

    .channel-desc {
      font-size: 11px;
      color: var(--text-secondary);
    }

    .channel-count {
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 4px;
      border: 1px solid currentColor;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }

    .safe-copy-box {
      font-family: var(--font-mono);
      font-size: 13px;
      line-height: 1.6;
      padding: 12px 14px;
      border: 1px solid var(--border-token);
      border-radius: 6px;
      background-color: var(--bg-viewport);
      color: var(--text-primary);
      white-space: pre-wrap;
      min-height: 120px;
    }

    .data-table-wrap {
      overflow-x: auto;
    }

    table.data-table {
      width: 100%;
      border-collapse: collapse;
      font-family: var(--font-mono);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }

    table.data-table th,
    table.data-table td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border-token);
      vertical-align: top;
    }

    table.data-table tr.highlighted-row {
      background-color: rgba(225, 29, 72, 0.10);
    }

    table.data-table th {
      color: var(--text-secondary);
      font-weight: 500;
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.03em;
    }

    .risk-badge {
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 600;
      font-size: 11px;
      border: 1px solid currentColor;
    }

    .risk-CRITICAL { color: var(--viz-rose); }
    .risk-HIGH     { color: var(--viz-amber); }
    .risk-MEDIUM   { color: var(--viz-indigo); }
    .risk-CLEAN    { color: var(--viz-emerald); }

    .legend-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-secondary);
    }

    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .legend-swatch {
      width: 10px;
      height: 10px;
      border-radius: 2px;
      display: inline-block;
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-left">
      <h1 class="brand-title">Pixel Guard</h1>
      <label class="load-image-btn-wrapper" id="load-image-btn" title="Select an image file to scan with Pixel Guard">
        <span id="load-image-btn-text">Load Image</span>
        <input
          type="file"
          id="load-image-file-input"
          accept=".png,.jpg,.jpeg,.webp,.bmp,.gif,.tif,.tiff,.pbm,.pgm,.ppm"
          aria-label="Load Image"
        />
      </label>
      <span class="feedback-banner" id="scan-feedback-banner" data-tone="neutral"></span>
    </div>
    <div class="nav-controls">
      <span class="status-pill" id="hdr-status" data-status="PASSED">PASSED</span>
      <div class="theme-selector" role="group" aria-label="Appearance Theme Selector">
        <button type="button" id="theme-btn-light" class="theme-btn" title="Light Theme" aria-label="Light Theme" data-theme-mode="light" aria-pressed="false">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="4"></circle>
            <line x1="12" y1="2" x2="12" y2="5"></line>
            <line x1="12" y1="19" x2="12" y2="22"></line>
            <line x1="4.93" y1="4.93" x2="7.05" y2="7.05"></line>
            <line x1="16.95" y1="16.95" x2="19.07" y2="19.07"></line>
            <line x1="2" y1="12" x2="5" y2="12"></line>
            <line x1="19" y1="12" x2="22" y2="12"></line>
            <line x1="4.93" y1="19.07" x2="7.05" y2="16.95"></line>
            <line x1="16.95" y1="7.05" x2="19.07" y2="4.93"></line>
          </svg>
        </button>
        <button type="button" id="theme-btn-dark" class="theme-btn" title="Dark Theme" aria-label="Dark Theme" data-theme-mode="dark" aria-pressed="false">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
        </button>
        <button type="button" id="theme-btn-system" class="theme-btn active" title="System Theme" aria-label="System Theme" data-theme-mode="system" aria-pressed="true">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
          </svg>
        </button>
      </div>
    </div>
  </header>

  <main class="bento-workspace">
    <section class="pane span-12">
      <div class="pane-header">
        <h2 class="pane-title">Scan Summary</h2>
        <span class="pane-meta" id="meta-filepath">--</span>
      </div>
      <div class="telemetry-strip">
        <div class="metric-cell">
          <div class="metric-label">Image File</div>
          <div class="metric-value" id="val-filename">--</div>
          <div class="metric-sub" id="val-format">--</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Dimensions</div>
          <div class="metric-value" id="val-dims">--</div>
          <div class="metric-sub" id="val-frames">--</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Section 1 (Safe Visible)</div>
          <div class="metric-value" id="val-visible" style="color: var(--viz-emerald);">0</div>
          <div class="metric-sub">WCAG CR &gt;= 3.0 &amp; Clean</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Section 2 (Quarantined)</div>
          <div class="metric-value" id="val-quarantined" style="color: var(--viz-rose);">0</div>
          <div class="metric-sub">Hidden or Injection Match</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Scan Time</div>
          <div class="metric-value" id="val-latency">0.0 ms</div>
          <div class="metric-sub" id="val-total-sub">0 total regions</div>
        </div>
      </div>
    </section>

    <section class="pane span-8">
      <div class="pane-header">
        <h2 class="pane-title">Inspected Image</h2>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <div class="segmented-group" role="group" aria-label="Image Render Mode">
            <button type="button" class="seg-btn active" id="view-btn-original">Original Image</button>
            <button type="button" class="seg-btn" id="view-btn-reveal">Enhanced Reveal</button>
          </div>
          <button type="button" class="action-btn active-toggle" id="toggle-boxes-btn">Boxes: On</button>
        </div>
      </div>
      <div class="image-viewport" id="image-viewport">
        <div class="image-frame-wrapper" id="image-frame-wrapper">
          <img id="inspected-image-el" class="inspected-img" alt="Inspected asset" />
          <svg id="bbox-overlay-svg" class="bbox-overlay-svg" preserveAspectRatio="none"></svg>
        </div>
        <div class="metadata-notice-pill" id="metadata-only-pill" style="display:none;">
          Non-pixel payload detected in file metadata (see Section 2)
        </div>
      </div>
      <div class="legend-bar">
        <span class="legend-item"><span class="legend-swatch" style="background:#059669;"></span>Section 1: Human-Visible Safe Text</span>
        <span class="legend-item"><span class="legend-swatch" style="background:#E11D48;"></span>Section 2: Critical Hidden / Injection</span>
        <span class="legend-item"><span class="legend-swatch" style="background:#D97706;"></span>Section 2: Camouflage / Anomaly Warning</span>
        <span class="pane-meta" id="reveal-hint-label">Switch to "Enhanced Reveal" to visualize camouflaged or transparent ink</span>
      </div>
    </section>

    <section class="pane span-4">
      <div class="pane-header">
        <h2 class="pane-title">Inspection Channels</h2>
        <span class="pane-meta">6 Live Pipeline Stages</span>
      </div>
      <div class="channel-list" id="channel-breakdown-list"></div>
    </section>

    <section class="pane span-5">
      <div class="pane-header">
        <h2 class="pane-title">Section 1: Human-Visible Text</h2>
        <button type="button" class="action-btn" id="copy-sec1-btn">Copy Safe Text</button>
      </div>
      <div class="safe-copy-box" id="sec1-text-box"></div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Line</th>
              <th>Box (x,y,w,h)</th>
              <th>Contrast</th>
              <th>dE_00</th>
              <th>FG / BG</th>
            </tr>
          </thead>
          <tbody id="sec1-tbody"></tbody>
        </table>
      </div>
    </section>

    <section class="pane span-7">
      <div class="pane-header">
        <h2 class="pane-title">Section 2: Quarantined &amp; Suspicious Findings</h2>
        <span class="pane-meta" id="sec2-summary-meta">0 items isolated</span>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Box #</th>
              <th>Severity</th>
              <th>Detection Channel</th>
              <th>Metrics</th>
              <th>Flags</th>
              <th>Extracted Text</th>
            </tr>
          </thead>
          <tbody id="sec2-tbody"></tbody>
        </table>
      </div>
    </section>
  </main>

  <script id="pixel-guard-empirical-bundle" type="application/json">__PIXEL_GUARD_JSON_PAYLOAD__</script>
  <script>
    (function () {
      const STORAGE_KEY = "pixel_guard_theme_mode";
      const EMBEDDED_STUDIO_URL = "__PIXEL_GUARD_STUDIO_URL__";
      const PALETTE = {
        teal: "#0D9488",
        amber: "#D97706",
        indigo: "#4F46E5",
        emerald: "#059669",
        rose: "#E11D48"
      };

      function resolveApiBase() {
        if (window.location.protocol === "http:" || window.location.protocol === "https:") {
          return window.location.origin;
        }
        if (EMBEDDED_STUDIO_URL && EMBEDDED_STUDIO_URL.indexOf("http") === 0) {
          return EMBEDDED_STUDIO_URL;
        }
        return "http://127.0.0.1:18765";
      }

      const API_BASE = resolveApiBase();

      let state = {
        report: JSON.parse(document.getElementById("pixel-guard-empirical-bundle").textContent),
        themeMode: localStorage.getItem(STORAGE_KEY) || "system",
        activeTheme: "light",
        imageViewMode: "original",
        showBoxes: true,
        selectedQuarantineId: null
      };

      const mediaQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

      function setFeedback(message, tone) {
        const banner = document.getElementById("scan-feedback-banner");
        if (!banner) return;
        banner.textContent = message;
        banner.setAttribute("data-tone", tone || "neutral");
      }

      function setScanningBusy(isBusy) {
        const wrap = document.getElementById("load-image-btn");
        const labelText = document.getElementById("load-image-btn-text");
        if (wrap) {
          wrap.classList.toggle("is-busy", isBusy);
        }
        if (labelText) {
          labelText.textContent = isBusy ? "Scanning..." : "Load Image";
        }
      }

      function resolveEffectiveTheme(mode) {
        if (mode === "light" || mode === "dark") {
          return mode;
        }
        if (mediaQuery && typeof mediaQuery.matches === "boolean") {
          return mediaQuery.matches ? "dark" : "light";
        }
        return (state.report && state.report.system_theme) ? state.report.system_theme : "light";
      }

      function applyTheme(mode) {
        state.themeMode = mode;
        try {
          localStorage.setItem(STORAGE_KEY, mode);
        } catch (_) {}
        state.activeTheme = resolveEffectiveTheme(mode);
        document.documentElement.setAttribute("data-theme", state.activeTheme);

        ["light", "dark", "system"].forEach(function (m) {
          const btn = document.getElementById("theme-btn-" + m);
          if (!btn) return;
          const isSelected = (m === mode);
          btn.classList.toggle("active", isSelected);
          btn.setAttribute("aria-pressed", isSelected ? "true" : "false");
        });

        renderVisualizations();
      }

      ["light", "dark", "system"].forEach(function (m) {
        const btn = document.getElementById("theme-btn-" + m);
        if (btn) {
          btn.addEventListener("click", function () {
            applyTheme(m);
          });
        }
      });

      if (mediaQuery) {
        const listener = function () {
          if (state.themeMode === "system") {
            applyTheme("system");
          }
        };
        if (mediaQuery.addEventListener) {
          mediaQuery.addEventListener("change", listener);
        } else if (mediaQuery.addListener) {
          mediaQuery.addListener(listener);
        }
      }

      function escapeHtml(str) {
        return String(str)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
      }

      function renderSummaryAndTables() {
        const r = state.report;
        const pill = document.getElementById("hdr-status");
        pill.textContent = r.scan_status;
        pill.setAttribute("data-status", r.scan_status);

        document.getElementById("meta-filepath").textContent = r.image_path;
        document.getElementById("val-filename").textContent = r.image_filename;
        document.getElementById("val-format").textContent = r.format + " (" + r.dimensions.channels + " channels)";
        document.getElementById("val-dims").textContent = r.dimensions.width + " x " + r.dimensions.height + " px";
        document.getElementById("val-frames").textContent = "Frames inspected: " + r.frames_analyzed + " / " + (r.frames_total || r.frames_analyzed);
        document.getElementById("val-visible").textContent = String(r.visible_count);
        document.getElementById("val-quarantined").textContent = String(r.quarantined_count);
        document.getElementById("val-latency").textContent = r.elapsed_ms.toFixed(1) + " ms";
        document.getElementById("val-total-sub").textContent = r.total_regions_found + " total text item(s)";

        const sec1Box = document.getElementById("sec1-text-box");
        const sec1Body = document.getElementById("sec1-tbody");
        if (r.section_1_visible_text.length === 0) {
          sec1Box.textContent = "[No verified human-visible safe text detected]";
          sec1Body.innerHTML = "<tr><td colspan=\"5\">Zero human-visible clean regions recorded.</td></tr>";
        } else {
          sec1Box.textContent = r.section_1_visible_text.map(function (item) { return item.text; }).join("\n");
          sec1Body.innerHTML = r.section_1_visible_text.map(function (item, idx) {
            return "<tr>" +
              "<td>V" + (idx + 1) + "</td>" +
              "<td>[" + item.bbox.join(", ") + "]</td>" +
              "<td>" + item.contrast_ratio.toFixed(2) + ":1</td>" +
              "<td>" + item.delta_e.toFixed(1) + "</td>" +
              "<td>" + escapeHtml(item.foreground_hex) + " / " + escapeHtml(item.background_hex) + "</td>" +
              "</tr>";
          }).join("");
        }

        const sec2Meta = document.getElementById("sec2-summary-meta");
        const sec2Body = document.getElementById("sec2-tbody");
        sec2Meta.textContent = r.section_2_quarantined_items.length + " item(s) isolated";
        if (r.section_2_quarantined_items.length === 0) {
          sec2Body.innerHTML = "<tr><td colspan=\"6\">No hidden, camouflaged, or prompt-injection payloads detected.</td></tr>";
        } else {
          sec2Body.innerHTML = r.section_2_quarantined_items.map(function (item) {
            const metricsParts = [];
            if (typeof item.contrast_ratio === "number") metricsParts.push("CR " + item.contrast_ratio.toFixed(2) + ":1");
            if (typeof item.delta_e === "number") metricsParts.push("dE " + item.delta_e.toFixed(1));
            if (typeof item.font_height_px === "number") metricsParts.push("H " + item.font_height_px + "px");
            if (typeof item.mean_alpha === "number" && item.mean_alpha < 0.999) metricsParts.push("Alpha " + item.mean_alpha.toFixed(2));
            const rowCls = state.selectedQuarantineId === item.item_id ? " class=\"highlighted-row\"" : "";
            return "<tr id=\"quar-row-" + item.item_id + "\"" + rowCls + ">" +
              "<td><strong>#" + item.item_id + "</strong></td>" +
              "<td><span class=\"risk-badge risk-" + escapeHtml(item.risk_level) + "\">" + escapeHtml(item.risk_level) + "</span></td>" +
              "<td>" + escapeHtml(item.detection_method) + "</td>" +
              "<td>" + (metricsParts.join(" | ") || "Metadata Container") + "</td>" +
              "<td>" + escapeHtml(item.security_flags.join(", ")) + "</td>" +
              "<td>" + escapeHtml(item.text) + "</td>" +
              "</tr>";
          }).join("");
        }
      }

      function renderInspectedImageAndBoxes() {
        const r = state.report;
        const imgEl = document.getElementById("inspected-image-el");
        const svgEl = document.getElementById("bbox-overlay-svg");
        const metaPill = document.getElementById("metadata-only-pill");
        const hintEl = document.getElementById("reveal-hint-label");
        if (!imgEl || !svgEl) return;

        const previews = r.preview_images || {};
        const activeUri = state.imageViewMode === "reveal"
          ? (previews.reveal_data_uri || previews.original_data_uri || "")
          : (previews.original_data_uri || "");

        if (activeUri) {
          imgEl.src = activeUri;
          imgEl.style.display = "block";
        } else {
          imgEl.removeAttribute("src");
          imgEl.style.display = "none";
        }

        if (hintEl) {
          if (state.imageViewMode === "reveal" && previews.reveal_frame_index > 0) {
            hintEl.textContent = "Showing Enhanced Reveal (Frame " + previews.reveal_frame_index + ")";
          } else if (state.imageViewMode === "reveal") {
            hintEl.textContent = "Showing Enhanced Reveal (contrast, chroma & alpha amplified)";
          } else {
            hintEl.textContent = "Switch to \"Enhanced Reveal\" to visualize invisible ink or alpha layers";
          }
        }

        const origW = Math.max(1, r.dimensions.width);
        const origH = Math.max(1, r.dimensions.height);
        svgEl.setAttribute("viewBox", "0 0 " + origW + " " + origH);

        const hasMetadataOnly = r.section_2_quarantined_items.length > 0 &&
          r.section_2_quarantined_items.every(function (q) { return !q.bbox; });
        if (metaPill) {
          metaPill.style.display = hasMetadataOnly ? "block" : "none";
        }

        if (!state.showBoxes || !activeUri) {
          svgEl.innerHTML = "";
          return;
        }

        const strokeScale = Math.max(2, Math.round(Math.max(origW, origH) / 380));
        const fontSize = Math.max(13, Math.round(Math.max(origW, origH) / 65));
        const pad = Math.max(4, strokeScale);
        let svgMarkup = "";

        // 1. Section 1 Verified Visible Boxes (Emerald)
        r.section_1_visible_text.forEach(function (v, idx) {
          const x = Math.max(0, v.bbox[0] - pad);
          const y = Math.max(0, v.bbox[1] - pad);
          const w = Math.min(origW - x, v.bbox[2] + pad * 2);
          const h = Math.min(origH - y, v.bbox[3] + pad * 2);
          const tagW = fontSize * 2.4;
          const tagH = fontSize * 1.38;
          const tagY = y >= tagH + 2 ? (y - tagH) : y;

          svgMarkup += "<g class=\"bbox-group\">" +
            "<title>Section 1 Visible (V" + (idx + 1) + "): " + escapeHtml(v.text) + " | CR " + v.contrast_ratio.toFixed(2) + ":1</title>" +
            "<rect class=\"bbox-stroke\" x=\"" + x + "\" y=\"" + y + "\" width=\"" + w + "\" height=\"" + h + "\" " +
              "fill=\"rgba(5, 150, 105, 0.12)\" stroke=\"" + PALETTE.emerald + "\" stroke-width=\"" + strokeScale + "\" rx=\"3\" />" +
            "<rect x=\"" + x + "\" y=\"" + tagY + "\" width=\"" + tagW + "\" height=\"" + tagH + "\" fill=\"" + PALETTE.emerald + "\" rx=\"2\" />" +
            "<text x=\"" + (x + fontSize * 0.35) + "\" y=\"" + (tagY + fontSize * 1.02) + "\" fill=\"#FFFFFF\" " +
              "font-family=\"'IBM Plex Mono', monospace\" font-weight=\"600\" font-size=\"" + fontSize + "\">V" + (idx + 1) + "</text>" +
            "</g>";
        });

        // 2. Section 2 Quarantined / Tampered Boxes (Deep Rose / Amber)
        r.section_2_quarantined_items.forEach(function (q) {
          if (!q.bbox) return;
          const isCrit = q.risk_level === "CRITICAL";
          const color = isCrit ? PALETTE.rose : PALETTE.amber;
          const fillRgba = isCrit ? "rgba(225, 29, 72, 0.16)" : "rgba(217, 119, 6, 0.16)";
          const x = Math.max(0, q.bbox[0] - pad);
          const y = Math.max(0, q.bbox[1] - pad);
          const w = Math.min(origW - x, q.bbox[2] + pad * 2);
          const h = Math.min(origH - y, q.bbox[3] + pad * 2);
          const label = "#" + q.item_id + " " + q.risk_level;
          const tagW = Math.max(fontSize * 5.8, label.length * fontSize * 0.64);
          const tagH = fontSize * 1.42;
          const tagY = y >= tagH + 2 ? (y - tagH) : (y + h);

          svgMarkup += "<g class=\"bbox-group\" data-quar-id=\"" + q.item_id + "\">" +
            "<title>Quarantined #" + q.item_id + " [" + escapeHtml(q.risk_level) + "]: " + escapeHtml(q.text) +
              " (" + escapeHtml(q.security_flags.join(", ")) + ")</title>" +
            "<rect class=\"bbox-stroke\" x=\"" + x + "\" y=\"" + y + "\" width=\"" + w + "\" height=\"" + h + "\" " +
              "fill=\"" + fillRgba + "\" stroke=\"" + color + "\" stroke-width=\"" + (strokeScale + 1) + "\" rx=\"3\" />" +
            "<rect x=\"" + x + "\" y=\"" + tagY + "\" width=\"" + tagW + "\" height=\"" + tagH + "\" fill=\"" + color + "\" rx=\"2\" />" +
            "<text x=\"" + (x + fontSize * 0.35) + "\" y=\"" + (tagY + fontSize * 1.03) + "\" fill=\"#FFFFFF\" " +
              "font-family=\"'IBM Plex Mono', monospace\" font-weight=\"600\" font-size=\"" + fontSize + "\">" + escapeHtml(label) + "</text>" +
            "</g>";
        });

        svgEl.innerHTML = svgMarkup;

        Array.prototype.forEach.call(svgEl.querySelectorAll("[data-quar-id]"), function (grp) {
          grp.addEventListener("click", function () {
            const qId = parseInt(grp.getAttribute("data-quar-id"), 10);
            state.selectedQuarantineId = qId;
            renderSummaryAndTables();
            const row = document.getElementById("quar-row-" + qId);
            if (row && row.scrollIntoView) {
              row.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
          });
        });
      }

      function renderChannelBreakdown() {
        const container = document.getElementById("channel-breakdown-list");
        if (!container) return;
        const r = state.report;
        const quar = r.section_2_quarantined_items;

        const specs = [
          {
            name: "RGB Baseline & Heuristics",
            desc: "Visible text OCR & prompt-injection signatures",
            match: function (q) { return q.origin_pass === "baseline"; },
            visCount: r.section_1_visible_text.length
          },
          {
            name: "Low-Contrast Reveal (Pass B)",
            desc: "Sub-threshold invisible ink (WCAG CR < 3.0)",
            match: function (q) { return q.origin_pass === "clahe_contrast" || q.security_flags.indexOf("LOW_CONTRAST_CAMOUFLAGE") !== -1; }
          },
          {
            name: "Chrominance Isolation (Pass C)",
            desc: "Iso-luminant CIE L*a*b* & HSV hue shifts",
            match: function (q) { return q.origin_pass === "perceptual_chroma" || q.security_flags.indexOf("CHROMINANCE_CAMOUFLAGE") !== -1; }
          },
          {
            name: "Alpha & Transparency (Pass D)",
            desc: "Near-zero opacity & zero-alpha raw RGB layers",
            match: function (q) { return (q.origin_pass || "").indexOf("alpha") === 0 || q.security_flags.indexOf("ALPHA_TRANSPARENCY_CAMOUFLAGE") !== -1; }
          },
          {
            name: "Edge, Micro-Text & Frames (Pass E/F)",
            desc: "Embossed bevels, <8px micro-fonts & flash frames",
            match: function (q) {
              return q.origin_pass === "edge_frequency" || q.origin_pass === "micro_upscale" ||
                q.security_flags.indexOf("MICRO_TEXT_ANOMALY") !== -1 ||
                q.security_flags.indexOf("INACTIVE_FRAME_OBFUSCATION") !== -1 ||
                q.security_flags.indexOf("MARGIN_BLEED_PLACEMENT") !== -1;
            }
          },
          {
            name: "Container Metadata",
            desc: "EXIF, PNG tEXt/iTXt, XMP XML & GIF comments",
            match: function (q) { return q.origin_pass === "metadata" || q.security_flags.indexOf("METADATA_CONTAINER_PAYLOAD") !== -1; }
          }
        ];

        container.innerHTML = specs.map(function (sp) {
          const hits = quar.filter(sp.match);
          const hasCrit = hits.some(function (h) { return h.risk_level === "CRITICAL"; });
          let badgeColor = PALETTE.emerald;
          let badgeText = sp.visCount ? (sp.visCount + " Safe") : "Clean";
          if (hits.length > 0) {
            badgeColor = hasCrit ? PALETTE.rose : PALETTE.amber;
            badgeText = hits.length + " Flagged";
          }
          return "<div class=\"channel-card\">" +
            "<div>" +
              "<div class=\"channel-name\">" + escapeHtml(sp.name) + "</div>" +
              "<div class=\"channel-desc\">" + escapeHtml(sp.desc) + "</div>" +
            "</div>" +
            "<span class=\"channel-count\" style=\"color:" + badgeColor + ";\">" + escapeHtml(badgeText) + "</span>" +
            "</div>";
        }).join("");
      }

      function renderVisualizations() {
        renderSummaryAndTables();
        renderInspectedImageAndBoxes();
        renderChannelBreakdown();
      }

      function setImageViewMode(mode) {
        state.imageViewMode = mode;
        const btnOrig = document.getElementById("view-btn-original");
        const btnRev = document.getElementById("view-btn-reveal");
        if (btnOrig) btnOrig.classList.toggle("active", mode === "original");
        if (btnRev) btnRev.classList.toggle("active", mode === "reveal");
        renderInspectedImageAndBoxes();
      }

      function applyNewScanReport(newReport) {
        state.report = newReport;
        state.selectedQuarantineId = null;
        setImageViewMode("original");
        renderVisualizations();
        const tone = newReport.scan_status === "PASSED"
          ? "ok"
          : (newReport.scan_status === "WARNING" ? "warn" : "error");
        setFeedback(
          "Executed Pixel Guard on " + newReport.image_filename + " -> " + newReport.scan_status +
          " (" + newReport.elapsed_ms.toFixed(1) + " ms)",
          tone
        );
      }

      function handleOfflineError() {
        setFeedback(
          "Local Pixel Guard server unreachable at " + API_BASE +
          ". Run: python3 scripts/pixel_guard_cli.py tests/images/clean_control.png",
          "error"
        );
      }

      function uploadAndExecuteSkill(fileObj) {
        if (!fileObj) return;
        setScanningBusy(true);
        setFeedback("Executing Pixel Guard pipeline on " + fileObj.name + "...", "neutral");

        // Immediately show browser-renderable formats while the Python pipeline executes
        const imgEl = document.getElementById("inspected-image-el");
        const svgEl = document.getElementById("bbox-overlay-svg");
        if (svgEl) svgEl.innerHTML = "";
        const lowerName = (fileObj.name || "").toLowerCase();
        const isBrowserNative = /\.(png|jpe?g|webp|gif|bmp)$/.test(lowerName);
        if (isBrowserNative && imgEl && typeof FileReader !== "undefined") {
          const reader = new FileReader();
          reader.onload = function (ev) {
            if (ev.target && typeof ev.target.result === "string") {
              imgEl.src = ev.target.result;
              imgEl.style.display = "block";
            }
          };
          reader.readAsDataURL(fileObj);
        }

        fetch(API_BASE + "/api/scan-upload", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": encodeURIComponent(fileObj.name)
          },
          body: fileObj
        })
          .then(function (resp) {
            return resp.json().then(function (body) {
              return { ok: resp.ok, body: body };
            });
          })
          .then(function (res) {
            setScanningBusy(false);
            if (!res.ok || res.body.error) {
              renderInspectedImageAndBoxes();
              setFeedback(
                "Blocked " + fileObj.name + " [" + (res.body.error_code || "SCAN_ERROR") + "]: " + (res.body.message || "Validation failed"),
                "error"
              );
              return;
            }
            applyNewScanReport(res.body);
          })
          .catch(function () {
            setScanningBusy(false);
            renderInspectedImageAndBoxes();
            handleOfflineError();
          });
      }

      (function bindInteractions() {
        const fileInput = document.getElementById("load-image-file-input");
        const btnOrig = document.getElementById("view-btn-original");
        const btnRev = document.getElementById("view-btn-reveal");
        const toggleBoxesBtn = document.getElementById("toggle-boxes-btn");

        if (fileInput) {
          fileInput.addEventListener("change", function () {
            if (fileInput.files && fileInput.files.length > 0) {
              const selected = fileInput.files[0];
              uploadAndExecuteSkill(selected);
              fileInput.value = "";
            }
          });
        }

        if (btnOrig) btnOrig.addEventListener("click", function () { setImageViewMode("original"); });
        if (btnRev) btnRev.addEventListener("click", function () { setImageViewMode("reveal"); });
        if (toggleBoxesBtn) {
          toggleBoxesBtn.addEventListener("click", function () {
            state.showBoxes = !state.showBoxes;
            toggleBoxesBtn.textContent = state.showBoxes ? "Boxes: On" : "Boxes: Off";
            toggleBoxesBtn.classList.toggle("active-toggle", state.showBoxes);
            renderInspectedImageAndBoxes();
          });
        }

        document.getElementById("copy-sec1-btn").addEventListener("click", function () {
          const text = document.getElementById("sec1-text-box").textContent;
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text);
          }
        });

        if (typeof EventSource !== "undefined") {
          try {
            const es = new EventSource(API_BASE + "/events");
            es.addEventListener("scan_update", function (evt) {
              const incoming = JSON.parse(evt.data);
              if (!state.report || incoming.sha256 !== state.report.sha256 || incoming.image_filename !== state.report.image_filename) {
                applyNewScanReport(incoming);
              }
            });
          } catch (_) {}
        }
      })();

      applyTheme(state.themeMode);
    })();
  </script>
</body>
</html>
"""
