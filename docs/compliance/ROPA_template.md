# Record of Processing Activities (RoPA) — Template

**Template version:** 1.0 (April 2026)
**Basis:** GDPR Article 30(1) / (2)

This template helps **organisations deploying
OpenConstructionERP on their own infrastructure** compile the
Record of Processing Activities that Article 30 of the General
Data Protection Regulation (Regulation (EU) 2016/679) requires
of most controllers and processors.

> **Scope note.**
> When you self-host OpenConstructionERP, **you are the
> controller** for the personal data you process. DDC has no
> access to that data and is not a processor. This template is
> provided as a starting point for *your own* RoPA; it is not
> binding on DDC.
>
> If you use a DDC-operated hosted instance under a separate
> commercial agreement, a DDC-specific RoPA and a Data
> Processing Agreement under Art. 28 GDPR are executed.

## How to use this template

1. Duplicate this file inside your own compliance repository,
   not here.
2. Fill in each row for each processing activity (not for
   each data type).
3. Update on material change (new module, new integration,
   new third-party processor).
4. Store the completed RoPA at a location accessible to your
   Data Protection Officer and, on request, to the supervisory
   authority.

## Part A — Controller record (Art. 30(1))

### A.1 Identification

| Field | Value |
|---|---|
| Name of controller | *Your organisation's legal name* |
| Address | *Registered address* |
| Representative (Art. 27 GDPR) | *If established outside the EU* |
| Data Protection Officer | *Name, email, phone (where Art. 37 applies)* |
| Supervisory authority | *Lead authority (Art. 56)* |

### A.2 Processing activities

Duplicate the following block for each activity.

#### Activity: *e.g. BOQ preparation for internal projects*

| Field | Value |
|---|---|
| Purpose of processing | *e.g. Preparing tenders, recording resource allocation* |
| Categories of data subjects | *Employees; suppliers; project stakeholders* |
| Categories of personal data | *Account data (email, password hash, display name); project notes; supplier contact details; labour rates linked to named roles* |
| Special categories (Art. 9) | *Typically none - confirm for each deployment* |
| Legal basis (Art. 6) | *Contract (6(1)(b)) for user accounts; legitimate interest (6(1)(f)) for supplier contacts; consent (6(1)(a)) for AI interaction logs* |
| Categories of recipients | *Internal staff; auditor; tax adviser; commissioned processors in §A.4* |
| International transfers | *None / SCC (EU 2021/914) / BCR / derogation - specify* |
| Retention period | *Per §A.3* |
| Technical and organisational measures | *Reference §A.5 and the product SECURITY.md* |

### A.3 Retention matrix

| Data category | Retention | Trigger | Source of obligation |
|---|---|---|---|
| Account data | Until account deletion | User action / offboarding | Contract |
| Project content | Until deletion; backups purged within 35 days | User action | Contract |
| Telemetry | 90 days | Time-based | Legitimate interest |
| Support correspondence | 24 months | Time-based | Legitimate interest |
| AI logs | 30 days | Time-based | Consent |
| Tax-relevant accounting extracts (DATEV) | 10 years | Year-end | German HGB § 257 / AO § 147 |

### A.4 Processors used (Art. 28)

| Processor | Role | Location | Safeguard |
|---|---|---|---|
| *Hetzner Online GmbH / AWS / Azure* | Infrastructure / hosting | *EEA / specify* | DPA executed; SCC if outside EEA |
| *Amazon SES / SendGrid / Postmark* | Email delivery | *EEA / US* | DPA + SCC |
| *Sentry* | Error reporting (optional) | EU / US | DPA + SCC |
| *OpenAI / Anthropic / Google / Mistral / Groq / DeepSeek* | AI inference (optional, user-configured) | US / EU / other | Each provider's DPA + SCC; user's TIA |

### A.5 Technical and organisational measures summary

(Cross-reference to full ISMS documentation; excerpt here.)

- Password hashing with bcrypt; JWT auth with configurable
  expiration.
- TLS 1.2+ in transit; encryption-at-rest recommended (see
  SECURITY.md).
- RBAC with least-privilege defaults; audit logs retained
  per §A.3.
- Backup-and-restore tested quarterly.
- Incident-response runbook aligned with GDPR Art. 33
  (72-hour notification) and Art. 34.
- Supplier onboarding with DPA signature prior to data
  access.

## Part B — Processor record (Art. 30(2))

*Fill in only if you act as a processor for a third-party
controller, e.g. if you host OpenConstructionERP on behalf of a
client.*

| Field | Value |
|---|---|
| Name of processor | *Your organisation* |
| Controllers served | *Client name(s) or contract identifier(s)* |
| Categories of processing | *Hosting, support, backup* |
| International transfers | *Specify* |
| TOMs | *Reference your ISMS; inherit OpenConstructionERP defaults* |

## Part C — Review and approval

| Event | Date | By |
|---|---|---|
| Template adopted | | |
| First completed draft | | |
| Next scheduled review | | |

---

*This template is provided as a baseline under CC BY 4.0. It is
not legal advice; have your DPO or data-protection counsel
review the completed RoPA before filing.*

Contact: `info@datadrivenconstruction.io`
