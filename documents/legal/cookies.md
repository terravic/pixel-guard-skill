# Cookie and Browser Storage Policy

> **DRAFT — REQUIRES LEGAL REVIEW**  
> This document is a starter template reflecting the technical behavior of `dashboard.html` as inspected in source code. It does not constitute legal advice and must be reviewed, completed, and approved by qualified legal counsel before publication.

**Effective Date:** `[EFFECTIVE_DATE]`  
**Publisher / Maintainer:** `[LEGAL_ENTITY_NAME]`  
**Privacy Contact:** `[DPO_CONTACT_EMAIL]`

---

## 1. Use of HTTP Cookies

`pixel-guard` and its local loopback dashboard (`dashboard.html`, served on `127.0.0.1`) set **zero HTTP cookies** (no session cookies, no analytics cookies, no advertising cookies, and no third-party tracking cookies).

---

## 2. Browser Local Storage

The standalone HTML dashboard (`dashboard.html`) uses a single strictly functional browser `localStorage` entry on the user's device:

| Storage Mechanism | Key | Purpose | Stored Values | Transmitted Off-Device? |
|---|---|---|---|---|
| `window.localStorage` | `pixel_guard_theme_mode` | Persists the user's UI appearance mode selection | `"light"`, `"dark"`, or `"system"` | Never |

No authentication tokens, credentials, scan images, or extracted text are written to `localStorage`, `sessionStorage`, `IndexedDB`, or cookies.

---

## 3. Third-Party Embeds, Fonts, and Trackers

`dashboard.html` loads zero external resources:
- Zero third-party scripts or stylesheets.
- Zero external web-font requests (uses local/system CSS font stacks enforced by `Content-Security-Policy`).
- Zero third-party embeds, captchas, or social widgets.

---

## 4. Managing Local Storage

You may remove `pixel_guard_theme_mode` at any time via your browser's Developer Tools (`Application -> Local Storage`) or site data clearing controls. Removing this key resets the dashboard appearance mode to `System`.

---

## 5. Contact

Questions regarding browser storage in `pixel-guard` may be directed to `[DPO_CONTACT_EMAIL]`.
