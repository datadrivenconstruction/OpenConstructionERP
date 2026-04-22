"""Compatibility shim — delegates to ``app.core.email``.

The real implementation was moved to ``app.core.email`` in v2.3.1 so the
rest of the app can plug in new transports (SES, SendGrid, …) without
touching integrations internals.  This module keeps the old import path
working for third-party modules and our own tests.

New code must import from ``app.core.email`` directly.
"""

from __future__ import annotations

import logging

from app.core.email import (
    EmailMessage,
    get_email_service,
    template_invoice_approved,
    template_meeting_invitation,
    template_password_reset,
    template_safety_alert,
    template_task_assigned,
)

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Backwards-compatible wrapper around ``EmailService.send``.

    Returns a plain ``bool`` to match the pre-2.3.1 signature; callers
    that want the structured ``DeliveryResult`` should use
    ``get_email_service().send(...)`` directly.
    """
    service = get_email_service()
    result = await service.send(EmailMessage(to=to, subject=subject, html_body=html_body))
    return result.ok


__all__ = [
    "send_email",
    "template_invoice_approved",
    "template_meeting_invitation",
    "template_password_reset",
    "template_safety_alert",
    "template_task_assigned",
]
