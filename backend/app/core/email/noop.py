"""No-op email backend.

Drops every message silently after a single DEBUG log line.  Intended
for automated test suites where you want the send path to execute (so
template rendering and service-layer logic is exercised) but do not
need to capture the result — use ``MemoryEmailBackend`` for that.

Distinct from the console backend: ``console`` logs at INFO so local
developers see output; ``noop`` stays quiet so pytest output is clean.
"""

from __future__ import annotations

import logging

from .base import BackendName, DeliveryResult, EmailBackend, EmailMessage

logger = logging.getLogger(__name__)


class NoopEmailBackend(EmailBackend):
    """Accept-and-drop transport."""

    name: BackendName = "noop"

    async def send(self, message: EmailMessage) -> DeliveryResult:
        logger.debug("[email:noop] dropped message to %s (%s)", message.to, message.subject)
        return DeliveryResult.success(self.name, reason="dropped")
