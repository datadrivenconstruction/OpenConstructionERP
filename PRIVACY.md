# Privacy Policy

**Effective date:** 2026-04-18
**Last updated:** 2026-04-18

This Privacy Policy describes how OpenConstructionERP ("the Software", "we")
handles personal data when you self-host the Software or use an instance
operated by DataDrivenConstruction ("DDC", the "Operator"). It is written
to satisfy the baseline transparency obligations of the EU General Data
Protection Regulation 2016/679 ("GDPR"), the United Kingdom Data
Protection Act 2018, the California Consumer Privacy Act / CPRA, and the
Brazilian Lei Geral de Proteção de Dados (LGPD).

> **Self-hosting note.** When you deploy the Software on your own
> infrastructure, **you become the data controller** for your users, and
> DDC has no access to any data. This document is then a template you may
> adapt for your own users. The operator-specific clauses below apply only
> to the instance at `https://openconstructionerp.com` operated by DDC.

---

## 1. Data we process

| Category | Examples | Legal basis |
|---|---|---|
| Account data | email, password hash, display name, locale | Contract (GDPR 6(1)(b)) |
| Authentication data | session tokens, API keys | Contract |
| Project content | BOQ items, documents, CAD/BIM files, annotations | Contract |
| Usage telemetry (anonymised) | page timings, error reports | Legitimate interest (GDPR 6(1)(f)) |
| Support correspondence | emails, issue comments | Legitimate interest |
| AI interaction logs (if configured) | prompts and responses | Consent (GDPR 6(1)(a)) |

We do **not** collect special-category data (GDPR Art. 9), nor do we sell
personal data as defined by the CCPA.

## 2. Where data is stored

- The Software stores all content in the database you configure
  (PostgreSQL or SQLite) and the object store you configure (local disk or
  S3-compatible).
- For the DDC-operated instance, servers are located in the European
  Economic Area. No personal data is transferred outside the EEA except
  under Standard Contractual Clauses (EU 2021/914) when an AI provider
  you have configured is based outside the EEA.

## 3. Retention

| Category | Default retention |
|---|---|
| Account data | Until account deletion |
| Project content | Until you delete it; deleted content is purged from backups within 35 days |
| Telemetry | 90 days |
| Support correspondence | 24 months |
| AI logs | 30 days unless you opt into a longer window |

## 4. Your rights

Under GDPR / UK DPA / LGPD you may:

- Access the personal data we hold about you (Art. 15)
- Rectify inaccurate data (Art. 16)
- Request erasure (Art. 17)
- Restrict or object to processing (Art. 18 / 21)
- Obtain your data in a portable format (Art. 20)
- Withdraw consent at any time

Under CCPA / CPRA you may additionally:

- Know what categories of personal information are collected
- Opt out of sale or sharing (we do not sell)
- Request deletion
- Not be discriminated against for exercising these rights

To exercise any right, email **privacy@datadrivenconstruction.io**. We
respond within 30 days (GDPR) or 45 days (CCPA).

## 5. Third-party processors

The DDC-operated instance uses these processors (self-hosted deployments
may use different providers):

- Infrastructure: Hetzner Online GmbH (EEA)
- Email delivery: Amazon SES (SCC in place)
- Error reporting: Sentry (optional)
- AI providers: **only those you enable**, with API keys you supply.
  Anthropic, OpenAI, Google, Mistral, Groq, DeepSeek each have their own
  privacy policy. Your prompts pass through the provider you selected.

## 6. Security

- Passwords hashed with bcrypt
- Transport over HTTPS / TLS 1.2+
- Database encryption-at-rest (recommended for self-hosters)
- Role-based access control with least-privilege defaults
- Security issues: see [SECURITY.md](SECURITY.md)

## 7. Cookies

See [COOKIES.md](COOKIES.md) for the cookie inventory.

## 8. Children

The Software is intended for professional use. We do not knowingly
process personal data of children under 16 (or under 13 in the US).

## 9. Changes

Material changes to this policy are announced via the release notes and,
for registered users on the DDC-operated instance, via email at least 30
days before taking effect.

## 10. Contact

- **Data controller (DDC instance):** DataDrivenConstruction, Artem Boiko
- **Email:** privacy@datadrivenconstruction.io
- **Supervisory authority:** the data-protection authority in your EU
  member state; for users in the UK, the Information Commissioner's
  Office (ICO).

---

*This stub policy is not a substitute for legal advice. Before relying on
this document for a production deployment with third-party users, have
it reviewed by a qualified privacy lawyer in the jurisdictions where you
offer the service.*
