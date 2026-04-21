# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in OpenConstructionERP,
please report it responsibly.

**DO NOT** open a public GitHub issue for security vulnerabilities.
Public disclosure before a fix is available puts users at risk.

### How to Report

1. **GitHub Security Advisories** (preferred):
   [Create a new advisory](https://github.com/datadrivenconstruction/OpenConstructionERP/security/advisories/new)

2. **Email:** `info@datadrivenconstruction.io`

### What to Include

- Description of the vulnerability
- Affected version (commit hash or release tag) and component
  (backend module, frontend, desktop client, Docker image)
- Steps to reproduce
- Potential impact (CIA classification and realistic scenarios)
- Suggested fix (if any)
- Your preferred credit attribution (or request for anonymity)

### Response Timeline

We follow coordinated disclosure:

| Action                | Target time                                              |
|-----------------------|----------------------------------------------------------|
| Acknowledgement       | 48 hours                                                 |
| Initial assessment    | 5 business days                                          |
| Fix development       | 14 business days (critical: 72 hours)                    |
| Public disclosure     | After a fix is released; at the latest 120 days from report |

For actively exploited vulnerabilities, we shorten all stages and
publish a mitigation advisory as soon as one is available.

## Supported Versions

| Version track          | Security updates                                    |
|------------------------|-----------------------------------------------------|
| `0.1.x` (current)      | Yes                                                 |
| Earlier 0.x releases   | No - upgrade path published in release notes        |

Once a `1.0.0` line is released, this matrix will be updated to
keep the latest stable plus the previous minor for six months.

## Scope

**In scope:**

- Backend API (FastAPI services under `backend/app/`)
- Frontend web application (`frontend/`)
- Desktop client (`desktop/`)
- Official Docker images published by DataDrivenConstruction and
  the DDC-operated instance at `https://openconstructionerp.com`
- CLI tools distributed with the project
- Build and release automation that produces signed artefacts
  (`.github/workflows/release*.yml`, `signatures/`)

**Out of scope:**

- Vulnerabilities in third-party dependencies - report directly
  to the upstream vendor; we will update once a patched version
  is available.
- Social engineering of Licensor, contributors, or customers.
- Issues that require an already-compromised user system or the
  user deliberately bypassing security controls.
- Self-XSS, denial-of-service via resource exhaustion on
  community-edition deployments.
- Issues restricted to configurations that contradict the
  self-hosting checklist below (e.g., default `JWT_SECRET`, HTTP
  instead of HTTPS).

## Self-Hosting Security Checklist

If you deploy OpenConstructionERP on your own infrastructure:

- [ ] Change `JWT_SECRET` from the default value
- [ ] Use HTTPS (TLS 1.2+) in production — never expose HTTP
      publicly
- [ ] Set `APP_ENV=production` to disable debug endpoints
      (`/api/docs`, `/api/redoc`)
- [ ] Use PostgreSQL with a strong password (not SQLite) for
      production
- [ ] Restrict `ALLOWED_ORIGINS` to your actual domain
- [ ] Keep Docker images updated (`docker compose pull`)
- [ ] Back up your database regularly and test restores
- [ ] Review `.env` file permissions — readable only by the app
      user
- [ ] If using AI features, protect your provider API keys
      (OpenAI / Anthropic / Google / Mistral / Groq / DeepSeek) —
      never commit them to git

## Security Features

- JWT authentication with configurable expiration
- Password hashing with bcrypt
- CORS middleware with configurable origins
- SQL-injection prevention via SQLAlchemy ORM
- Input validation via Pydantic v2
- Rate limiting (configurable)
- Role-based access control (RBAC)
- Reproducible builds and signed release artefacts
  (see `signatures/`)

## Regulatory Reporting

Where required by EU Regulation 2024/2847 (Cyber Resilience Act,
vulnerability-reporting obligations effective 11 September 2026),
we report actively exploited vulnerabilities through the ENISA
Single Reporting Platform and cooperate with the German Federal
Office for Information Security (BSI) / CERT-Bund.

The DDC-operated instance additionally complies with GDPR
Art. 33 personal-data-breach notification (72 hours to the
competent supervisory authority).

## No Bug Bounty

DataDrivenConstruction currently does not operate a paid
bug-bounty programme. We gratefully acknowledge responsible
researchers in the associated GitHub Security Advisories unless
anonymity is requested.

## Contact

All security communication: `info@datadrivenconstruction.io`.
Where GitHub Security Advisories are available, please use that
channel for reports that include sensitive proof-of-concept
material.
