"""SMTP email backend.

Wraps ``smtplib.SMTP`` with async-friendly semantics: the blocking
handshake + send runs in ``asyncio.to_thread`` so the event loop stays
responsive during the typical 100–500 ms round-trip.

Configuration comes from ``app.config.Settings``:

    ``smtp_host``     — required; empty disables the backend (returns a
                        structured "not configured" ``DeliveryResult``).
    ``smtp_port``     — 587 for STARTTLS, 465 for implicit TLS (we use
                        STARTTLS via ``smtp_tls=True``).
    ``smtp_user``     — optional; when set we LOGIN before sending.
    ``smtp_password`` — optional; pairs with ``smtp_user``.
    ``smtp_from``     — default ``From:`` address.
    ``smtp_tls``      — enable STARTTLS upgrade.

The backend builds a multipart/alternative message with both a plain-text
and HTML part so inbox-provider scoring stays reasonable (pure-HTML
emails are often flagged as spam).  The plain-text fallback is a very
rough strip of HTML tags — good enough for receipts and resets.
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import Settings

from .base import BackendName, DeliveryResult, EmailBackend, EmailMessage

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """Strip HTML tags for the plain-text MIME alternative."""
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _WHITESPACE_RE.sub(" ", text).strip()


class SmtpEmailBackend(EmailBackend):
    """Production SMTP transport."""

    name: BackendName = "smtp"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _configured(self) -> bool:
        return bool(self._settings.smtp_host)

    async def send(self, message: EmailMessage) -> DeliveryResult:
        if not self._configured():
            # Surface the gap loudly — silent failure made this endpoint
            # look healthy while users never received reset emails
            # (observed during the v2.3.1 audit).
            logger.warning(
                "[email:smtp] dropping message to %s — SMTP not configured "
                "(set SMTP_HOST to enable the smtp backend)",
                message.to,
            )
            return DeliveryResult.failure(self.name, reason="smtp not configured")

        try:
            return await asyncio.to_thread(self._send_sync, message)
        except Exception:  # noqa: BLE001 — we must convert any exception to a structured result
            logger.exception("[email:smtp] unexpected failure delivering to %s", message.to)
            return DeliveryResult.failure(self.name, reason="unexpected error")

    def _send_sync(self, message: EmailMessage) -> DeliveryResult:
        settings = self._settings
        from_addr = message.from_addr or settings.smtp_from

        mime = MIMEMultipart("alternative")
        mime["From"] = from_addr
        mime["To"] = message.to
        mime["Subject"] = message.subject
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        for k, v in message.headers.items():
            mime[k] = v
        mime.attach(MIMEText(_html_to_text(message.html_body), "plain", "utf-8"))
        mime.attach(MIMEText(message.html_body, "html", "utf-8"))

        try:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            try:
                server.ehlo()
                if settings.smtp_tls:
                    server.starttls()
                    server.ehlo()
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(from_addr, [message.to], mime.as_string())
            finally:
                try:
                    server.quit()
                except smtplib.SMTPException:
                    # Connection may already be closed by the server — fine.
                    pass
            logger.info(
                "[email:smtp] sent to=%s subject=%r tags=%s",
                message.to,
                message.subject,
                message.tags or "-",
            )
            return DeliveryResult.success(self.name)
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("[email:smtp] auth failed for %s: %s", settings.smtp_user, exc)
            return DeliveryResult.failure(self.name, reason="auth failed")
        except smtplib.SMTPRecipientsRefused as exc:
            logger.warning("[email:smtp] recipient refused %s: %s", message.to, exc)
            return DeliveryResult.failure(self.name, reason="recipient refused")
        except smtplib.SMTPException as exc:
            logger.exception("[email:smtp] smtp error delivering to %s: %s", message.to, exc)
            return DeliveryResult.failure(self.name, reason=f"smtp error: {type(exc).__name__}")
        except OSError as exc:
            # Network-level: DNS failure, connection refused, timeout.
            logger.exception(
                "[email:smtp] network error delivering to %s: %s", message.to, exc
            )
            return DeliveryResult.failure(self.name, reason=f"network error: {type(exc).__name__}")
