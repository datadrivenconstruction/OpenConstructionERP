# Email / SMTP setup

Context: marketing site has a **Commercial license request form** (`/pro/breeze/#license`)
that POSTs JSON to `/api/v1/inquiries/license`. Backend already has an async SMTP
service (`backend/app/modules/integrations/email_service.py`) but no public endpoint
wired yet.

---

## 1 — What's already in the repo

| Piece | Location | Status |
|---|---|---|
| Async SMTP sender | `backend/app/modules/integrations/email_service.py` | ✅ done — uses `smtplib`, supports TLS, HTML templates |
| SMTP config keys | `backend/app/config.py` (`smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_tls`) | ✅ done |
| Contacts CRUD | `backend/app/modules/contacts/` | ✅ done (auth-gated) |
| Public rate-limited pattern | `POST /api/v1/users/auth/register` | ✅ done — template to follow |
| Public inquiry endpoint | — | ❌ missing |
| `LicenseInquiry` model | — | ❌ missing |
| External transactional API (SendGrid / Mailgun / Resend) | — | ❌ none — raw SMTP only |

---

## 2 — Minimal backend work to wire the form

Add a module `backend/app/modules/inquiries/` with:

```
inquiries/
├── manifest.py          # auto_install=True, depends=["oe_users"]
├── models.py            # LicenseInquiry(id, name, email, company, team_size, use_case, message, created_at, ip, status)
├── schemas.py           # LicenseInquiryIn, LicenseInquiryOut
├── router.py            # POST /api/v1/inquiries/license  — NO auth, rate-limited per IP (e.g. 5/hour)
├── service.py           # save to DB + call email_service.send_email(to=settings.sales_inbox, ...)
├── migrations/          # Alembic
└── tests/
```

Router outline:

```python
# backend/app/modules/inquiries/router.py
from fastapi import APIRouter, Request, Depends
from slowapi.util import get_remote_address
from app.modules.integrations.email_service import EmailService
from . import schemas, service

router = APIRouter(prefix="/api/v1/inquiries", tags=["inquiries"])

@router.post("/license", response_model=schemas.LicenseInquiryOut, status_code=201)
async def submit_license_request(
    payload: schemas.LicenseInquiryIn,
    request: Request,
    email: EmailService = Depends(),
) -> schemas.LicenseInquiryOut:
    # Rate-limit 5/hour per IP (add limiter decorator)
    inquiry = await service.create_inquiry(payload, ip=get_remote_address(request))
    await email.send(
        to=settings.sales_inbox,
        subject=f"Commercial license request — {payload.company}",
        template="license_request",
        ctx=payload.model_dump(),
    )
    return inquiry
```

CORS: `/api/v1/inquiries/*` must allow `openconstructionerp.com` + `localhost:8765` in
dev. Adjust `ALLOWED_ORIGINS` in `.env`.

---

## 3 — Hooking up your own SMTP server

The backend talks to any SMTP server. Set these in `.env`:

```env
SMTP_HOST=mail.yourco.com
SMTP_PORT=587           # 587 = STARTTLS, 465 = implicit TLS
SMTP_USER=noreply@yourco.com
SMTP_PASSWORD=          # app password or service account
SMTP_FROM="OpenConstructionERP <noreply@yourco.com>"
SMTP_TLS=true
SALES_INBOX=sales@openconstructionerp.com
```

You need three things on the mail server side:

1. **MX + SPF + DKIM + DMARC DNS records** for the sending domain. Without DKIM and
   DMARC, Gmail/Outlook will junk every outbound message.
2. **Reverse DNS (PTR)** for the sending IP matching the HELO hostname. Required by
   strict receivers.
3. **An authenticated SMTP submission user** (port 587 usually). Never expose port 25
   for authenticated submission.

If the app server and mail server are different machines, open egress from app → mail
on 587 (or 465). Nothing else.

---

## 4 — Open-source / self-hosted options

Ranked by how much operational work each one takes. **Postal** is the sweet spot for
transactional use (form submissions, password resets) — not for marketing blasts.

| Option | Best for | Footprint | Notes |
|---|---|---|---|
| **[Postal](https://postalserver.io/)** | Transactional SMTP + REST API | Docker stack (Ruby + MariaDB + RabbitMQ) | Modern, webhooks, bounce handling, great dashboard. Our preferred choice. |
| **[Mailcow](https://mailcow.email/)** | Full mail stack (receive + send + IMAP + webmail) | Docker compose, ~3 GB RAM | Overkill if you only send outbound, but if you want real mailboxes at `@yourco.com` it's the easiest. Postfix + Dovecot + Rspamd + SOGo under the hood. |
| **[Mail-in-a-Box](https://mailinabox.email/)** | Full mail stack, opinionated install | Single Ubuntu VM | One-command setup but expects to own the whole box. No Docker. |
| **[Postfix + Dovecot](http://www.postfix.org/)** | DIY classic stack | Bare Linux | Maximum control, maximum yak-shaving. Use only if you already admin mail servers. |
| **[Listmonk](https://listmonk.app/)** | Newsletter / bulk campaigns | Go + Postgres | Not transactional — complementary if you ever want a mailing list. |
| **[Docker Mailserver](https://docker-mailserver.github.io/)** | Compact Postfix+Dovecot image | Single container | Lighter than Mailcow, more DIY than Postal. |

### Recommendation

For our case (form submissions to `sales@`), run **Postal** as a dedicated container
on the same VPS as the ERP. The app points at it via `SMTP_HOST=postal.internal`,
Postal delivers outbound with DKIM signing, and you get a dashboard of every message
with delivery status / bounce logs.

Alternatively, if you don't want to operate a mail server at all, **Resend** (not
OSS, but free 3,000/month) or **Amazon SES** are cheap drop-ins that speak plain SMTP
— nothing in the backend changes, only `SMTP_HOST`.

---

## 5 — Frontend fallback today

Until the `/api/v1/inquiries/license` endpoint is live, the form on `#license` does:

1. Submit via `fetch()` to `data-api="/api/v1/inquiries/license"`.
2. On network/API failure, surfaces a **"Backend offline — open email client"** link
   that `mailto:`-prefills `sales@openconstructionerp.com` with all the form fields.

So the site is shippable now; the backend work unblocks *proper* submissions but is
not blocking for deploy.
