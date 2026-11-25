# Privacy Policy

> **DRAFT — REQUIRES LEGAL REVIEW**  
> This document is a starter template reflecting the technical behavior of `pixel-guard-skill` as inspected in source code. It does not constitute legal advice and must be reviewed, completed, and approved by qualified legal counsel before publication.

**Effective Date:** `[EFFECTIVE_DATE]`  
**Data Controller / Maintainer:** `[LEGAL_ENTITY_NAME]`  
**Registered Address:** `[MAILING_ADDRESS]`  
**Privacy Contact / DPO:** `[DPO_CONTACT_EMAIL]`  
**Repository:** `[REPOSITORY_URL]`

---

## 1. Scope

This Privacy Policy describes how `[LEGAL_ENTITY_NAME]` handles data when users download, install, or run the `pixel-guard` local image sanitization software (`pixel-guard-skill`), including its CLI (`scripts/pixel_guard_cli.py`), stdio MCP server (`scripts/mcp_server.py`), `PreToolUse` hook (`scripts/pre_tool_hook.py`), and loopback dashboard (`dashboard.html`).

---

## 2. Local-Only Data Processing Architecture

`pixel-guard` executes deterministically on the user's local machine:

- **Zero Telemetry or Analytics:** The software does not collect, transmit, or report usage telemetry, crash logs, IP addresses, or device fingerprints to `[LEGAL_ENTITY_NAME]` or any third party.
- **Zero External API or LLM Calls:** Image validation, metadata extraction, computer vision passes, local Tesseract OCR, colorimetric math, and regex heuristics run entirely offline with zero outbound network requests.
- **Zero Databases or Accounts:** The software does not operate user accounts, remote databases, or cloud storage buckets.

---

## 3. Categories of Local Transient Data

When a user scans an image locally, the software processes the image file and any text or container metadata contained inside that image (which may include personal data if present in the user's chosen document):

| Local Data Artifact | Purpose | Storage Location | Retention and Erasure |
|---|---|---|---|
| Uploaded image bytes (`POST /api/scan-upload`) | Temporary staging for local scanning via `dashboard.html` | Ephemeral OS temporary directory (`pixel_guard_upload_*`) | Deleted immediately upon scan completion |
| OCR intermediate frames | Local Tesseract TSV execution | Ephemeral OS temporary directory (`pixel_guard_ocr_*`) | Deleted immediately upon OCR subprocess exit |
| Root `dashboard.html` | Offline visual inspection of the most recent scan | Local repository root (`dashboard.html`) or `--dashboard` path | Persists on local disk until overwritten by the next scan or deleted by the user (`rm dashboard.html`) |
| Loopback session token | Authenticating local `file://` dashboard requests to `127.0.0.1` | Per-user `0700` temp directory (`0600` file) | Deleted automatically on Studio server shutdown |
| Browser appearance setting | Remembering Light, Dark, or System UI preference | Browser `localStorage` (`pixel_guard_theme_mode`) | Persists locally until cleared via browser storage settings |

---

## 4. Third-Party Sub-Processors and Cross-Border Transfers

- **Runtime Sub-Processors:** None. `pixel-guard` invokes zero third-party cloud APIs, CDNs, font hosts, or remote processors at runtime.
- **Code Hosting Platform:** If you access this repository through `[CODE_HOSTING_PROVIDER]` (for example, submitting issues or pull requests), that platform processes account and connection metadata under its own privacy policy: `[CODE_HOSTING_PRIVACY_URL]`.
- **Cross-Border Transfers:** Because all image processing occurs strictly on the user's local host, `[LEGAL_ENTITY_NAME]` performs no cross-border transfer of scanned image content. `[INSERT_REGIONAL_DISCLOSURES_IF_HOSTED_DEPLOYMENT_ADDED]`

---

## 5. Data Subject Rights (GDPR / CCPA / Applicable Laws)

Because `[LEGAL_ENTITY_NAME]` does not receive, store, or control images scanned locally by `pixel-guard`:

- **Access & Portability:** Users hold direct local access to all scan outputs in structured machine-readable JSON (`--format json`) and Markdown (`--format markdown`).
- **Erasure (Right to be Forgotten):** Users can immediately erase all local scan artifacts by deleting `dashboard.html`, any user-specified `--output` files, and clearing browser `localStorage` for `pixel_guard_theme_mode`.
- **Inquiries:** For any privacy request concerning communications or repository contributions held by `[LEGAL_ENTITY_NAME]`, contact `[DPO_CONTACT_EMAIL]`. Statutory response SLA: `[RESPONSE_SLA_DAYS]` days (30 days under GDPR).

---

## 6. Changes to This Policy

Material updates will be published in `[REPOSITORY_URL]` with an updated Effective Date (`[EFFECTIVE_DATE]`).
