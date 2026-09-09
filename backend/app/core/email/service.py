# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Email service facade - the public seam the rest of the app talks to.

Responsibilities:

* Pick the right backend based on ``Settings.email_backend``.
* Provide high-level, typed helpers (``send_password_reset``, …) so
  call sites never assemble raw ``EmailMessage`` objects or worry about
  template subjects.
* Log every attempt at INFO with structured fields for observability.
* Memoise the backend per ``Settings`` instance so production workloads
  do not re-create SMTP clients on every send.

Testing hook: ``get_email_service(backend=...)`` accepts an explicit
backend instance, letting tests inject a ``MemoryEmailBackend`` without
monkey-patching settings.

Why a facade instead of passing the backend directly?  Call sites
outnumber backends roughly 20:1 - keeping a single ``get_email_service``
entry point means adding a new provider (SES, SendGrid) is a two-file
change (``base.py`` + the new backend) rather than a sweep across
modules/users, modules/integrations, and any future consumer.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.core.demo_accounts import is_demo_account

from .base import BackendName, DeliveryResult, EmailAttachment, EmailBackend, EmailMessage
from .console import ConsoleEmailBackend
from .memory import MemoryEmailBackend
from .noop import NoopEmailBackend
from .smtp import SmtpEmailBackend
from .templates import template_password_reset, wrap

logger = logging.getLogger(__name__)


#: Where an operator can read the whole outbound-email setup in prose.
EMAIL_SETUP_DOC = "docs/email-setup.md"


def email_delivery_enabled(settings: Settings) -> bool:
    """True when the settings select a transport that actually delivers mail.

    The single definition of "email is really configured".  Call sites that
    want to tell a user whether mail will leave the building must use this
    rather than testing ``email_backend`` or ``smtp_host`` on their own -
    two spellings of the same rule drift apart, and the half that is wrong
    is the half nobody tests.
    """
    return settings.email_backend == "smtp" and bool(settings.smtp_host)


def console_delivery_expected(settings: Settings) -> bool:
    """True when console is about to stand in for a transport that was wanted.

    Answers the one question that separates a supported setup from a silent
    defect, because the *value* of ``email_backend`` cannot: an air-gapped
    install that wrote ``EMAIL_BACKEND=console`` and a server whose operator
    wrote nothing about email at all both read ``console``.
    ``model_fields_set`` is what distinguishes them - pydantic records which
    fields any source actually supplied, so writing the value in ``.env``, in
    the environment or in the constructor all count as choosing it, and only a
    completely untouched field is absent.

    Development is exempt outright. A fresh checkout has to run without any
    configuration, and that is the whole reason the field carries this default.
    """
    if settings.app_env == "development":
        return False
    if settings.email_backend == "smtp":
        # Delivery was asked for in the loudest way the settings allow; the
        # resolver below still hands back console when the host is empty.
        return True
    return "email_backend" not in settings.model_fields_set


def diagnose_email_config(settings: Settings) -> str | None:
    """Return a human-readable problem with the outbound email settings.

    Returns ``None`` when the settings are coherent, which includes the
    perfectly valid "no outbound email configured at all" case - an install
    that never sends mail is supported and must not nag.

    This exists because every one of these mistakes used to be silent.  The
    worst of them, filling in every ``SMTP_*`` variable while leaving
    ``EMAIL_BACKEND`` at its ``console`` default, produced a *successful*
    delivery result and a log line that looked like a send, so the operator
    had nothing at all to go on.  Each message below names the setting that
    is wrong and the value that would fix it.
    """
    backend = settings.email_backend
    smtp_fields_set = any(
        (settings.smtp_host, settings.smtp_user, settings.smtp_password),
    )

    if backend != "smtp" and smtp_fields_set:
        return (
            f"SMTP settings are present but EMAIL_BACKEND is {backend!r}, so no mail is sent - "
            f"the {backend!r} transport only records messages. Set EMAIL_BACKEND=smtp to deliver "
            f"them. See {EMAIL_SETUP_DOC}."
        )

    if backend == "console" and console_delivery_expected(settings):
        # The check above cannot reach this shape: it needs an SMTP_* variable
        # to be present, and here none of them are. That is the whole reason a
        # measured production install ran log-only for ten days with every
        # instrument reporting health - there was no contradiction to find,
        # only an absence, and an absence is invisible to a check that reads
        # values instead of asking which of them a human supplied.
        return (
            f"EMAIL_BACKEND was never set, so this APP_ENV={settings.app_env!r} deployment runs "
            f"on the 'console' transport: password resets, tender invitations and document "
            f"emails are written to this log and never leave the building, and nobody waiting "
            f"for one is told. Set EMAIL_BACKEND=smtp together with SMTP_HOST to deliver them, "
            f"or set EMAIL_BACKEND=console explicitly to record that a log-only transport is "
            f"intended - this message stops either way. See {EMAIL_SETUP_DOC}."
        )

    if backend == "smtp" and not settings.smtp_host:
        return (
            f"EMAIL_BACKEND=smtp but SMTP_HOST is empty, so no mail can be sent. "
            f"Set SMTP_HOST to your provider's submission server. See {EMAIL_SETUP_DOC}."
        )

    if backend == "smtp" and settings.smtp_port == 465:
        return (
            "SMTP_PORT=465 expects implicit TLS, which this transport does not speak - it "
            "connects in the clear and upgrades with STARTTLS, so port 465 stalls until the "
            f"connection times out. Use SMTP_PORT=587 with SMTP_TLS=true. See {EMAIL_SETUP_DOC}."
        )

    if backend == "smtp" and settings.smtp_port == 587 and not settings.smtp_tls:
        return (
            "SMTP_PORT=587 is a STARTTLS port but SMTP_TLS is false, so credentials would be "
            f"sent in the clear and most providers will refuse. Set SMTP_TLS=true. See {EMAIL_SETUP_DOC}."
        )

    if backend == "smtp" and settings.smtp_user and not settings.smtp_password:
        return (
            "SMTP_USER is set but SMTP_PASSWORD is empty, so the connection is made without "
            "authentication and a submission relay will refuse it. Note the setting is "
            f"SMTP_PASSWORD, not SMTP_PASS. See {EMAIL_SETUP_DOC}."
        )

    return None


def report_email_config_at_startup(settings: Settings) -> None:
    """Say at boot what the transport would otherwise only say on first send.

    ``_resolve_backend`` already logs the same diagnosis, but lazily: the
    backend is built on the first send, so the warning arrives after somebody
    has already waited for a password reset that never came. This runs while
    the operator is still reading the boot log.

    Severity follows the environment rather than the finding. Outside
    development an unconfigured transport is a defect an operator has to act
    on, so it goes out at ERROR. In development the only diagnoses that can
    fire are real contradictions the developer typed themselves, and those
    stay at WARNING - a zero-config checkout must reach the end of its boot
    log without a single ERROR line, or the ERROR lines that matter stop being
    read.
    """
    problem = diagnose_email_config(settings)
    if problem is None:
        return
    if settings.app_env == "development":
        logger.warning("[email] %s", problem)
    else:
        logger.error("[email] %s", problem)


def _resolve_backend(settings: Settings) -> EmailBackend:
    """Instantiate the backend named in settings.

    ``smtp`` falls back to ``console`` when ``smtp_host`` is empty so a
    developer who ticked ``EMAIL_BACKEND=smtp`` in .env but forgot to
    fill in credentials still sees reset emails in the log instead of a
    silent drop.  Production deployments should set ``EMAIL_BACKEND=smtp``
    AND provide host/credentials - the SMTP backend logs a warning when
    host is missing so operators notice immediately.
    """
    problem = diagnose_email_config(settings)
    if problem:
        logger.warning("[email] %s", problem)

    expected = console_delivery_expected(settings)
    name: BackendName = settings.email_backend
    if name == "smtp":
        if not settings.smtp_host:
            return ConsoleEmailBackend(delivery_expected=expected)
        return SmtpEmailBackend(settings)
    if name == "console":
        return ConsoleEmailBackend(delivery_expected=expected)
    if name == "noop":
        return NoopEmailBackend()
    if name == "memory":
        return MemoryEmailBackend()
    # Defensive - Pydantic's Literal type narrows ``name`` to the four
    # values above, so this branch is only reachable if an upstream
    # version adds a new backend without updating the resolver.
    raise ValueError(f"Unknown email backend: {name!r}")


class EmailService:
    """High-level email operations used by feature modules."""

    def __init__(self, backend: EmailBackend) -> None:
        self._backend = backend

    @property
    def backend_name(self) -> str:
        return self._backend.name

    async def send(self, message: EmailMessage) -> DeliveryResult:
        """Low-level send - use the typed helpers below when possible."""
        if is_demo_account(message.to):
            # The seeded demo logins are not mailboxes. Sending to them
            # produces a hard bounce on a domain we own, which is what cost
            # the account its outbound privileges in September 2026. The
            # guard sits here rather than in the notification dispatcher
            # because six other modules reach the transport directly, and a
            # rail placed on one of seven paths is not a rail.
            logger.warning(
                "email refused: recipient is a seeded demo login, not a mailbox: to=%s subject=%r",
                message.to,
                message.subject,
            )
            return DeliveryResult.failure(self._backend.name, "recipient is a demo login, not a mailbox")
        result = await self._backend.send(message)
        if not result.ok:
            logger.warning(
                "email delivery failed: backend=%s reason=%s to=%s subject=%r",
                result.backend,
                result.reason,
                message.to,
                message.subject,
            )
        return result

    async def send_password_reset(
        self,
        to: str,
        reset_url: str,
        recipient_name: str | None = None,
        token_lifetime_minutes: int = 60,
    ) -> DeliveryResult:
        """Send a password-reset email. Returns the delivery result.

        ``reset_url`` must already embed the signed token as a query
        parameter.  Never log the URL at INFO - the token is sensitive.
        """
        subject, html = template_password_reset(
            recipient_name=recipient_name,
            reset_url=reset_url,
            token_lifetime_minutes=token_lifetime_minutes,
        )
        # Log intent at INFO without the URL; the backend logs the subject.
        logger.info("sending password-reset email to %s via %s", to, self._backend.name)
        return await self.send(
            EmailMessage(to=to, subject=subject, html_body=html, tags=["password_reset"]),
        )

    async def send_document(
        self,
        to: str,
        *,
        subject: str,
        document_name: str,
        attachment: EmailAttachment,
        recipient_name: str | None = None,
        sender_name: str | None = None,
        note: str | None = None,
    ) -> DeliveryResult:
        """Email a generated document (PDF) as an attachment.

        Used by feature modules that produce a PDF on the fly (Property
        Development receipts / contracts / certificates) and want to send
        it straight to a buyer or counterparty. The body is a short cover
        note; the document itself rides as ``attachment``.
        """
        greeting = f"Hi {recipient_name}," if recipient_name else "Hello,"
        from_line = f" from {sender_name}" if sender_name else ""
        note_html = (
            f"<blockquote style='border-left:3px solid #0071e3; padding-left:12px; "
            f"margin:12px 0; color:#1d1d1f;'>{note}</blockquote>"
            if note
            else ""
        )
        body = (
            f"<p>{greeting}</p>"
            f"<p>Please find attached your <strong>{document_name}</strong>{from_line}.</p>"
            f"{note_html}"
            f"<p style='font-size:13px; color:#6e6e73;'>The document is attached to this "
            f"email as a PDF.</p>"
        )
        html = wrap(document_name, body)
        logger.info(
            "sending document email to=%s document=%r via %s",
            to,
            document_name,
            self._backend.name,
        )
        return await self.send(
            EmailMessage(
                to=to,
                subject=subject,
                html_body=html,
                tags=["document", document_name],
                attachments=[attachment],
            ),
        )


@lru_cache(maxsize=4)
def _cached_service(settings_id: int) -> EmailService:
    """Per-Settings-instance cache so we do not rebuild the backend per send.

    Keyed by ``id(settings)`` (Settings is unhashable because some fields
    are lists).  ``get_settings`` in turn uses its own ``lru_cache``, so
    in practice we get exactly one service per process.
    """
    settings = get_settings()  # Trust the global singleton.
    # ``settings_id`` is the cache key; we ignore it in the body - its only
    # job is to give lru_cache a distinct entry per Settings instance.
    _ = settings_id
    return EmailService(_resolve_backend(settings))


def get_email_service(backend: EmailBackend | None = None) -> EmailService:
    """Return a process-singleton ``EmailService``.

    Pass ``backend`` explicitly from tests to bypass settings resolution:

        service = get_email_service(backend=MemoryEmailBackend())
    """
    if backend is not None:
        return EmailService(backend)
    settings = get_settings()
    return _cached_service(id(settings))


def reset_email_service_cache() -> None:
    """Drop the cached service - used by tests that mutate settings."""
    _cached_service.cache_clear()
