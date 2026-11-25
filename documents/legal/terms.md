# Terms of Use

> **DRAFT — REQUIRES LEGAL REVIEW**  
> This document is a starter template and does not constitute legal advice. It must be reviewed, completed, and approved by qualified legal counsel before publication.

**Effective Date:** `[EFFECTIVE_DATE]`  
**Publisher / Maintainer:** `[LEGAL_ENTITY_NAME]`  
**Contact Email:** `[CONTACT_EMAIL]`  
**Governing Jurisdiction:** `[GOVERNING_JURISDICTION]`  
**Repository:** `[REPOSITORY_URL]`

---

## 1. Acceptance and Open-Source License

`pixel-guard-skill` is distributed as open-source software under the **Apache License, Version 2.0** (see [LICENSE](../../LICENSE)). By downloading, installing, copying, or executing the software, you agree to comply with the Apache-2.0 license terms and these Terms of Use where applicable. In the event of conflict regarding software copyright or patent licensing, the Apache License, Version 2.0 controls.

---

## 2. Intended Use and Security Boundaries

`pixel-guard` is a deterministic pre-flight image inspection utility designed to detect low-contrast text, transparency masking, micro-typography, container metadata payloads, and pattern-matched visual prompt-injection signatures prior to multimodal ingestion.

- **No Absolute Security Guarantee:** Deterministic heuristics and local OCR reduce visual prompt-injection exposure but do not guarantee detection of all novel, adversarial, or obfuscated inputs. Operators remain responsible for defense-in-depth controls, least-privilege tool scoping, and human review of untrusted files.
- **Local Execution Responsibility:** You are solely responsible for securing the host machine, local workspace files, and any generated `dashboard.html` or `--output` reports containing sensitive documents.

---

## 3. Prohibited Conduct

You agree not to use `[LEGAL_ENTITY_NAME]` trademarks, project identifiers, or distribution channels to:
- Distribute tampered builds misrepresenting origin or security guarantees.
- Violate applicable laws, export controls, or third-party intellectual property rights.

---

## 4. Disclaimer of Warranties and Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW AND CONSISTENT WITH SECTIONS 7 AND 8 OF THE APACHE LICENSE, VERSION 2.0, THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.

IN NO EVENT SHALL `[LEGAL_ENTITY_NAME]` OR CONTRIBUTORS BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES ARISING FROM USE OF OR INABILITY TO USE THE SOFTWARE.

`[INSERT_JURISDICTION_SPECIFIC_LIABILITY_CARVEOUTS]`

---

## 5. Governing Law and Dispute Resolution

These Terms are governed by the laws of `[GOVERNING_JURISDICTION]`, excluding conflict-of-law principles. `[INSERT_VENUE_OR_ARBITRATION_CLAUSE]`

---

## 6. Contact

Questions regarding these Terms may be directed to `[CONTACT_EMAIL]`.
