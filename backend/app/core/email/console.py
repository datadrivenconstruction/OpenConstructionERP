"""Console email backend — logs structured records instead of sending.

Purpose: zero-config default for local development.  A fresh checkout
runs without MSA credentials, but developers still need to see *what*
the app would have sent (subject, recipient, body preview) so they can
test password-reset and notification flows without a real SMTP server.

The backend is also a useful fallback in production for environments
where outbound SMTP is intentionally disabled (air-gapped installs,
compliance freezes) — operators see every attempted send in the app log
instead of a silent no-op.
"""

from __future__ import annotations

import logging

from .base import BackendName, DeliveryResult, EmailBackend, EmailMessage

logger = logging.getLogger(__name__)


class ConsoleEmailBackend(EmailBackend):
    """Log messages to the application logger at INFO level.

    Body is truncated to 500 characters in the log line so a multi-KB HTML
    email does not dominate the log file — the full body is still emitted
    at DEBUG if you need it for template debugging.
    """

    name: BackendName = "console"

    async def send(self, message: EmailMessage) -> DeliveryResult:
        preview = message.html_body[:500]
        logger.info(
            "[email:console] to=%s subject=%r tags=%s preview=%s%s",
            message.to,
            message.subject,
            message.tags or "-",
            preview,
            "…" if len(message.html_body) > 500 else "",
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[email:console] full body for %s:\n%s", message.to, message.html_body)
        return DeliveryResult.success(self.name, reason="logged")
