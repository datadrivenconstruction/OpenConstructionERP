# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SMTP email backend.

Wraps ``smtplib.SMTP`` with async-friendly semantics: the blocking
handshake + send runs in ``asyncio.to_thread`` so the event loop stays
responsive during the typical 100–500 ms round-trip.

Configuration comes from ``app.config.Settings``:

    ``smtp_host``     - required; empty disables the backend (returns a
                        structured "not configured" ``DeliveryResult``).
    ``smtp_port``     - 587 for STARTTLS, 465 for implicit TLS (we use
                        STARTTLS via ``smtp_tls=True``).
    ``smtp_user``     - optional; when set we LOGIN before sending.
    ``smtp_password`` - optional; pairs with ``smtp_user``.
    ``smtp_from``     - default ``From:`` address.
    ``smtp_tls``      - enable STARTTLS upgrade.

The backend builds a multipart/alternative message with both a plain-text
and HTML part so inbox-provider scoring stays reasonable (pure-HTML
emails are often flagged as spam).  The plain-text alternative is derived
from the HTML body by ``html_text.html_to_text``, which keeps link targets
- everything the recipient needs is in the text part, not only in the HTML
one.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import Settings

from .base import BackendName, DeliveryResult, EmailBackend, EmailMessage
from .html_text import html_to_text as _html_to_text

logger = logging.getLogger(__name__)


class SmtpEmailBackend(EmailBackend):
    """Production SMTP transport."""

    name: BackendName = "smtp"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _configured(self) -> bool:
        return bool(self._settings.smtp_host)

    def _unsupported_port_combination(self) -> str | None:
        """Name a port/encryption pairing this transport cannot honour.

        Port 465 is implicit TLS: the server expects a TLS handshake before
        it says anything.  This backend always opens a cleartext connection
        first and upgrades with STARTTLS, so against a 465 server neither
        side speaks and the connection sits there until the socket timeout -
        fifteen seconds of nothing, then a bare "connection unexpectedly
        closed" that names neither the port nor the encryption.  Refusing up
        front turns that into an instant, actionable message.
        """
        if self._settings.smtp_port == 465:
            return (
                "SMTP_PORT=465 requires implicit TLS, which this transport does not support; "
                "use SMTP_PORT=587 with SMTP_TLS=true"
            )
        return None

    async def send(self, message: EmailMessage) -> DeliveryResult:
        blocker = self._unsupported_port_combination()
        if blocker:
            logger.error("[email:smtp] not sending to %s - %s", message.to, blocker)
            return DeliveryResult.failure(self.name, reason=blocker)

        if not self._configured():
            # Surface the gap loudly - silent failure made this endpoint
            # look healthy while users never received reset emails
            # (observed during the v2.3.1 audit).
            logger.warning(
                "[email:smtp] dropping message to %s - SMTP not configured (set SMTP_HOST to enable the smtp backend)",
                message.to,
            )
            return DeliveryResult.failure(self.name, reason="smtp not configured")

        try:
            return await asyncio.to_thread(self._send_sync, message)
        except Exception:  # noqa: BLE001 - we must convert any exception to a structured result
            logger.exception("[email:smtp] unexpected failure delivering to %s", message.to)
            return DeliveryResult.failure(self.name, reason="unexpected error")

    def _send_sync(self, message: EmailMessage) -> DeliveryResult:
        settings = self._settings
        from_addr = message.from_addr or settings.smtp_from

        # Body is always multipart/alternative (plain + HTML). When the
        # message carries attachments we wrap that body in a multipart/mixed
        # envelope so MUAs render the text and offer the files for download.
        body = MIMEMultipart("alternative")
        body.attach(MIMEText(_html_to_text(message.html_body), "plain", "utf-8"))
        body.attach(MIMEText(message.html_body, "html", "utf-8"))

        if message.attachments:
            mime = MIMEMultipart("mixed")
            mime.attach(body)
            for att in message.attachments:
                subtype = (att.content_type.split("/", 1) or ["application", "octet-stream"])[-1]
                part = MIMEApplication(att.content, _subtype=subtype)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=att.filename,
                )
                mime.attach(part)
        else:
            mime = body

        mime["From"] = from_addr
        mime["To"] = message.to
        mime["Subject"] = message.subject
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        for k, v in message.headers.items():
            mime[k] = v

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
                    # Connection may already be closed by the server - fine.
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
        except smtplib.SMTPNotSupportedError as exc:
            # Almost always STARTTLS asked of a server that does not offer it.
            logger.error(
                "[email:smtp] %s:%s refused a requested extension (%s) - the server does not offer "
                "STARTTLS on this port; check SMTP_PORT and SMTP_TLS against the provider's submission settings",
                settings.smtp_host,
                settings.smtp_port,
                exc,
            )
            return DeliveryResult.failure(
                self.name,
                reason="server does not support STARTTLS on this port - check SMTP_PORT and SMTP_TLS",
            )
        except smtplib.SMTPServerDisconnected as exc:
            # A silent socket: a firewall dropping egress and a server that
            # wanted implicit TLS look identical from here, so name both.
            logger.error(
                "[email:smtp] %s:%s closed the connection without completing the exchange (%s) - the "
                "outbound port may be blocked, or the server may expect implicit TLS on this port",
                settings.smtp_host,
                settings.smtp_port,
                exc,
            )
            return DeliveryResult.failure(
                self.name,
                reason="server disconnected or timed out - check SMTP_PORT and outbound firewall",
            )
        except smtplib.SMTPSenderRefused as exc:
            # The server rejected the envelope sender, and two unrelated causes
            # arrive as this one exception. The response code separates them:
            # 530/535 means it wanted authentication it never got, while 550/553
            # means the account is not allowed to send as this address. The class
            # name says "sender refused" either way, which sent people looking at
            # the wrong setting.
            if exc.smtp_code in (530, 535):
                reason = "authentication required - set SMTP_USER and SMTP_PASSWORD"
                hint = "the server requires authentication; note the setting is SMTP_PASSWORD, not SMTP_PASS"
            else:
                reason = "sender address refused - check SMTP_FROM"
                hint = "the account is not allowed to send as this address; set SMTP_FROM to one it owns"
            logger.error(
                "[email:smtp] %s:%s refused the sender %s with %s - %s",
                settings.smtp_host,
                settings.smtp_port,
                exc.sender,
                exc.smtp_code,
                hint,
            )
            return DeliveryResult.failure(self.name, reason=reason)
        except smtplib.SMTPException as exc:
            logger.exception("[email:smtp] smtp error delivering to %s: %s", message.to, exc)
            return DeliveryResult.failure(self.name, reason=f"smtp error: {type(exc).__name__}")
        except OSError as exc:
            # Network-level: DNS failure, connection refused, timeout. A traceback
            # tells the operator nothing they can act on here - the host and port
            # they typed are the whole of the answer.
            logger.error(
                "[email:smtp] cannot reach %s:%s (%s) - check SMTP_HOST and SMTP_PORT, and that "
                "outbound connections to that port are allowed",
                settings.smtp_host,
                settings.smtp_port,
                exc,
            )
            return DeliveryResult.failure(
                self.name,
                reason=f"cannot reach {settings.smtp_host}:{settings.smtp_port} - check SMTP_HOST and SMTP_PORT",
            )
