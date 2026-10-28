# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Console email backend - logs structured records instead of sending.

Purpose: zero-config default for local development.  A fresh checkout
runs without MSA credentials, but developers still need to see *what*
the app would have sent (subject, recipient, body preview) so they can
test password-reset and notification flows without a real SMTP server.

The backend is also a useful fallback in production for environments
where outbound SMTP is intentionally disabled (air-gapped installs,
compliance freezes) - operators see every attempted send in the app log
instead of a silent no-op.

Those two audiences want opposite answers from ``send``, which is what
``delivery_expected`` decides.  An operator who wrote ``EMAIL_BACKEND=console``
asked for a log-only transport and got one, so the log line *is* the delivery
and reporting success is honest.  A deployment that merely never set the
variable is running on a field default nobody picked, and telling it the send
worked removes the last signal anyone had: no failure log, no error to the
caller, and afterwards no way to name who never got their mail.
"""

from __future__ import annotations

import logging

from .base import BackendName, DeliveryResult, EmailBackend, EmailMessage

logger = logging.getLogger(__name__)


class ConsoleEmailBackend(EmailBackend):
    """Log messages to the application logger at INFO level.

    Body is truncated to 500 characters in the log line so a multi-KB HTML
    email does not dominate the log file - the full body is still emitted
    at DEBUG if you need it for template debugging.
    """

    name: BackendName = "console"

    def __init__(self, *, delivery_expected: bool = False) -> None:
        """Args:
        delivery_expected: True when this deployment expects mail to actually
            leave and console is standing in for a transport nobody selected.
            ``send`` then reports failure instead of success. Defaults to
            False so local development, tests and a deliberately chosen
            log-only transport all keep the historical behaviour.
        """
        self._delivery_expected = delivery_expected

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
        if self._delivery_expected:
            # Deliberately short and free of operator instructions: this string
            # reaches end users, e.g. as the detail of the 502 the Property
            # Development document mailer raises. What to change, and where it
            # is written down, goes to the operator through
            # ``diagnose_email_config`` and the boot log instead.
            return DeliveryResult.failure(
                self.name,
                "no outbound email transport is configured on this server, so the message "
                "was written to the server log instead of being delivered",
            )
        return DeliveryResult.success(self.name, reason="logged")
