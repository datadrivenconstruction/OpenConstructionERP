"""Pluggable email service for OpenConstructionERP.

Public API (import from ``app.core.email``):

    - EmailMessage          — value object describing a single email
    - DeliveryResult        — structured send outcome (never raises)
    - EmailBackend          — ABC for custom transports
    - EmailService          — facade used by feature modules
    - get_email_service     — returns a process-cached ``EmailService``
    - reset_email_service_cache — test helper

    Template helpers (``template_*``) are re-exported from
    ``app.core.email.templates`` for convenience.

Example::

    from app.core.email import get_email_service

    service = get_email_service()
    await service.send_password_reset(
        to=user.email,
        reset_url=f"{settings.frontend_url}/reset?token={token}",
        recipient_name=user.full_name,
    )

Backends supported out of the box (pick via ``EMAIL_BACKEND``):

    console — log to app logger at INFO (default for local dev)
    smtp    — real SMTP delivery (production)
    noop    — drop silently (CI)
    memory  — capture into a list for test assertions

Add a new transport by subclassing ``EmailBackend`` and wiring it into
``service._resolve_backend``.
"""

from .base import DeliveryResult, EmailBackend, EmailMessage
from .console import ConsoleEmailBackend
from .memory import MemoryEmailBackend
from .noop import NoopEmailBackend
from .service import EmailService, get_email_service, reset_email_service_cache
from .smtp import SmtpEmailBackend
from .templates import (
    template_invoice_approved,
    template_meeting_invitation,
    template_password_reset,
    template_safety_alert,
    template_task_assigned,
    wrap,
)

__all__ = [
    "ConsoleEmailBackend",
    "DeliveryResult",
    "EmailBackend",
    "EmailMessage",
    "EmailService",
    "MemoryEmailBackend",
    "NoopEmailBackend",
    "SmtpEmailBackend",
    "get_email_service",
    "reset_email_service_cache",
    "template_invoice_approved",
    "template_meeting_invitation",
    "template_password_reset",
    "template_safety_alert",
    "template_task_assigned",
    "wrap",
]
