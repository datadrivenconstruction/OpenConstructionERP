"""In-memory email backend for assertion-based tests.

Captures every sent message in a list that tests can introspect:

    >>> backend = MemoryEmailBackend()
    >>> await backend.send(EmailMessage(to="a@x", subject="hi", html_body="<p/>"))
    >>> assert backend.sent[0].subject == "hi"

Separate from ``NoopEmailBackend`` (which discards and stays quiet) so
test files that *assert* on email content can do so without paying the
cost of that bookkeeping in production code paths.
"""

from __future__ import annotations

from .base import BackendName, DeliveryResult, EmailBackend, EmailMessage


class MemoryEmailBackend(EmailBackend):
    """Capture-in-list transport for tests."""

    name: BackendName = "memory"

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> DeliveryResult:
        self.sent.append(message)
        return DeliveryResult.success(self.name, reason="captured")

    def clear(self) -> None:
        self.sent.clear()
