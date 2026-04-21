# SOC 2 Type I Readiness

**Version 1.0 — April 2026**

This document describes the state of readiness of
OpenConstructionERP and of the DDC-operated hosted instance
against the AICPA Trust Services Criteria (TSC) 2017 (revised
2022). It is intended for enterprise procurement teams asking
"are you SOC 2 ready?".

> This is a **self-attested readiness statement**, not an
> audit report. A SOC 2 Type I report will be produced after an
> independent CPA engagement; until then, this document lists
> the controls that are implemented today.

## 1. Scope

- Software: OpenConstructionERP (all modules distributed under
  AGPL-3.0-or-later and the commercial licence).
- Systems: the DDC-operated hosted instance at
  <https://openconstructionerp.com> (if and when operated),
  including the production database, object storage, and
  release-automation pipeline.
- Subservice organisations: Hetzner Online GmbH (or equivalent
  IaaS), email delivery provider (Amazon SES or equivalent),
  optional error-reporting (Sentry). These are treated under
  the **carve-out method**.

## 2. Trust Services Criteria mapping

### 2.1 Security (common criteria) — CC series

| Control ID | Description | Implementation |
|---|---|---|
| CC1.1 | Code of Conduct | Published as CODE_OF_CONDUCT.md (Contributor Covenant). Enforcement via info@datadrivenconstruction.io. |
| CC2.1 | Board / owner oversight | Sole proprietor governance; single-owner decision log maintained in private repo. |
| CC3.2 | Risk identification | Annual threat-model review (STRIDE) for backend and frontend; logged in private ISMS. |
| CC5.2 | Policies | LICENSE, NOTICE, SECURITY, PRIVACY, TERMS, COOKIES, CLA, PATENTS, TRADEMARK, ACCESSIBILITY, EXPORT-COMPLIANCE all published and maintained in this repository. |
| CC6.1 | Access controls | RBAC with least-privilege defaults; admin role separation; MFA required on admin accounts. |
| CC6.3 | Credential management | Bcrypt password hashing; JWT with configurable expiration; no default secrets in production (startup check enforces). |
| CC6.6 | Logical segmentation | Docker-compose isolates services; production ALLOWED_ORIGINS restricts CORS. |
| CC6.7 | Data in transit | TLS 1.2+ enforced; HSTS on the hosted instance. |
| CC7.1 | Detection | Sentry (optional); structured logs via structlog; CRA-aligned vulnerability reporting channel (SECURITY.md). |
| CC7.2 | Monitoring | `/health` and `/metrics` endpoints; release pipeline publishes CycloneDX SBOM. |
| CC7.4 | Incident response | SECURITY.md response timelines (48h acknowledgement / 5 business-days assessment / 14 business-days fix for critical / 72h fix for critical). GDPR Art. 33 72-hour supervisory-authority notification path documented. |
| CC8.1 | Change management | GitHub-Flow with required review on main (CODEOWNERS); release-please automation; signed releases (cosign, Sigstore) pinned in `.github/workflows/release-signing.yml`; pre-commit hooks (ruff, eslint). |
| CC9.1 | Risk mitigation in vendor relationships | Subservice organisations carved out (§1); DPAs executed; SCCs where outside EEA. |

### 2.2 Availability — A series

| Control ID | Description | Implementation |
|---|---|---|
| A1.1 | Capacity planning | Resource monitoring on hosted instance; horizontal-scaling readiness via Docker compose profiles. |
| A1.2 | Backup and recovery | Automated daily backups; quarterly restore drill; documented in operational runbook. |
| A1.3 | Environmental controls | Carved out to Hetzner Online GmbH (ISO 27001 certified). |

### 2.3 Confidentiality — C series

| Control ID | Description | Implementation |
|---|---|---|
| C1.1 | Identification of confidential information | Documented in PRIVACY.md and in the internal data-classification matrix. |
| C1.2 | Handling of confidential information | Encryption in transit (TLS); encryption at rest recommended (deployer responsibility in self-hosting context). |

### 2.4 Processing Integrity — PI series (for accounting / DATEV / ELSTER modules)

| Control ID | Description | Implementation |
|---|---|---|
| PI1.1 | Input validation | Pydantic v2 at API boundary; frontend Zod schemas mirror backend contracts. |
| PI1.4 | Processing completeness | Idempotency keys on financial endpoints; audit trail via accounting ledger. |
| PI1.5 | Output reconciliation | GAEB X86 and DATEV export validators; signed report checksums. |

### 2.5 Privacy — P series (for the DDC-operated instance)

| Control ID | Description | Implementation |
|---|---|---|
| P1.1 | Notice to data subjects | PRIVACY.md published at the hosted instance. |
| P2.1 | Consent capture | Cookie-banner consent (see COOKIES.md); AI-interaction opt-in. |
| P4.1 | Access | GDPR Art. 15 handled within 30 days via info@datadrivenconstruction.io. |
| P5.1 | Disclosure to third parties | Sub-processor list maintained; notification on material change (30-day advance notice for the hosted instance). |
| P6.2 | Incident response | GDPR Art. 33 72-hour supervisory-authority notification; Art. 34 data-subject notification when required. |
| P8.1 | Monitoring and enforcement | Annual self-review against this readiness document; external audit on procurement demand. |

## 3. Gaps vs full SOC 2 Type I

To produce a full Type I report the following are still
required:

- Engagement of a licensed CPA firm (typical 6-8 weeks).
- Formal policy signatures with effective dates (ISMS
  formalisation).
- Evidence collection for the chosen effective period.
- Management assertion letter.

## 4. Supporting artefacts available on request

- Internal ISMS policy documents (access-control, change-
  management, incident-response, data-classification,
  retention).
- Subservice-organisation SOC 2 / ISO 27001 reports
  (Hetzner, Amazon SES).
- CycloneDX SBOM for the current release (auto-generated on
  each GitHub release - see
  `.github/workflows/sbom-and-licenses.yml`).
- Signed release artefacts and Sigstore transparency-log
  entries (see `.github/workflows/release-signing.yml`).

## 5. Roadmap to Type I

| Milestone | Target |
|---|---|
| ISMS formalisation (signed policies) | Q3 2026 |
| Evidence-collection period begins | Q4 2026 |
| SOC 2 Type I report issued | Q2 2027 |
| SOC 2 Type II (12-month operating effectiveness) | Q2 2028 |

## 6. Contact

`info@datadrivenconstruction.io` — procurement, questionnaire
completion, and audit coordination.
