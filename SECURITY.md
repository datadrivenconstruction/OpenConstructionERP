# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in OpenConstructionERP, please report it responsibly.

**DO NOT** open a public GitHub issue for security vulnerabilities.

### How to Report

1. **GitHub Security Advisories** (preferred):
   Go to [Security Advisories](https://github.com/datadrivenconstruction/OpenConstructionERP/security/advisories/new) and create a new advisory.

2. **Email**: info@datadrivenconstruction.io

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

| Action | Timeframe |
|--------|-----------|
| Acknowledgment | 48 hours |
| Initial assessment | 5 business days |
| Fix development | 14 business days (critical: 72 hours) |
| Public disclosure | After fix is released |

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Self-Hosting Security Checklist

If you deploy OpenConstructionERP on your own infrastructure:

- [ ] Change `JWT_SECRET` from the default value
- [ ] Use HTTPS (TLS) in production — never expose HTTP publicly
- [ ] Set `APP_ENV=production` to disable debug endpoints (`/api/docs`, `/api/redoc`)
- [ ] Use PostgreSQL with a strong password (not SQLite) for production
- [ ] Restrict `ALLOWED_ORIGINS` to your actual domain
- [ ] Keep Docker images updated (`docker compose pull`)
- [ ] Back up your database regularly
- [ ] Review `.env` file permissions — should be readable only by the app user
- [ ] If using AI features, protect your API keys (OpenAI/Anthropic) — never commit them

## Security Features

- JWT authentication with configurable expiration
- Password hashing with bcrypt
- CORS middleware with configurable origins
- SQL injection prevention via SQLAlchemy ORM
- Input validation via Pydantic v2
- Rate limiting (configurable)
- Role-based access control (RBAC)
