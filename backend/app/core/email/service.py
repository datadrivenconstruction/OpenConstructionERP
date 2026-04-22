"""Email service facade — the public seam the rest of the app talks to.

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
outnumber backends roughly 20:1 — keeping a single ``get_email_service``
entry point means adding a new provider (SES, SendGrid) is a two-file
change (``base.py`` + the new backend) rather than a sweep across
modules/users, modules/integrations, and any future consumer.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import Settings, get_settings

from .base import BackendName, DeliveryResult, EmailBackend, EmailMessage
from .console import ConsoleEmailBackend
from .memory import MemoryEmailBackend
from .noop import NoopEmailBackend
from .smtp import SmtpEmailBackend
from .templates import template_password_reset

logger = logging.getLogger(__name__)


def _resolve_backend(settings: Settings) -> EmailBackend:
    """Instantiate the backend named in settings.

    ``smtp`` falls back to ``console`` when ``smtp_host`` is empty so a
    developer who ticked ``EMAIL_BACKEND=smtp`` in .env but forgot to
    fill in credentials still sees reset emails in the log instead of a
    silent drop.  Production deployments should set ``EMAIL_BACKEND=smtp``
    AND provide host/credentials — the SMTP backend logs a warning when
    host is missing so operators notice immediately.
    """
    name: BackendName = settings.email_backend
    if name == "smtp":
        if not settings.smtp_host:
            logger.warning(
                "EMAIL_BACKEND=smtp but SMTP_HOST is empty — falling back to console backend. "
                "Set SMTP_HOST to enable real delivery.",
            )
            return ConsoleEmailBackend()
        return SmtpEmailBackend(settings)
    if name == "console":
        return ConsoleEmailBackend()
    if name == "noop":
        return NoopEmailBackend()
    if name == "memory":
        return MemoryEmailBackend()
    # Defensive — Pydantic's Literal type narrows ``name`` to the four
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
        """Low-level send — use the typed helpers below when possible."""
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
        parameter.  Never log the URL at INFO — the token is sensitive.
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


@lru_cache(maxsize=4)
def _cached_service(settings_id: int) -> EmailService:
    """Per-Settings-instance cache so we do not rebuild the backend per send.

    Keyed by ``id(settings)`` (Settings is unhashable because some fields
    are lists).  ``get_settings`` in turn uses its own ``lru_cache``, so
    in practice we get exactly one service per process.
    """
    settings = get_settings()  # Trust the global singleton.
    # ``settings_id`` is the cache key; we ignore it in the body — its only
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
    """Drop the cached service — used by tests that mutate settings."""
    _cached_service.cache_clear()
