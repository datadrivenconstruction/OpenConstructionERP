"""Core email abstractions.

Defines the ``EmailMessage`` value object and the ``EmailBackend`` protocol
that every concrete backend (console, smtp, noop, memory) must satisfy.

Backends are intentionally small — a single async ``send`` method — so new
transports (SES, SendGrid, Mailgun, …) can be added as plugins without
touching call sites.  Everything above the backend (template rendering,
retries, logging, settings) lives in ``service.py``.

The backend API is *advisory* about failure: ``send`` returns a
``DeliveryResult`` with ``ok`` plus a structured reason instead of raising.
That lets the service layer log every attempt uniformly and lets callers
decide whether a failed notification is fatal (rare — most emails are
"nice to have" beside a persisted state change).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class EmailMessage:
    """A single outbound email.

    Kept as a dumb data container so backends can serialize it freely
    (e.g. the memory backend stores a list of these for test assertions).

    Attributes:
        to: Recipient address. Always a single string — use multiple
            ``EmailMessage`` objects if you need to fan out, so per-recipient
            delivery status stays independent.
        subject: Pre-rendered subject line. Templates produce this.
        html_body: Rendered HTML body. Plain-text is derived by the SMTP
            backend when needed (strip tags + entities).
        from_addr: Optional ``From:`` override. Falls back to
            ``settings.smtp_from`` in the SMTP backend.
        reply_to: Optional ``Reply-To:`` header.
        headers: Extra headers (e.g. ``List-Unsubscribe``). Keys are
            case-insensitive per RFC 5322.
        tags: Free-form labels for observability (``["password_reset"]``).
            Used by the console backend for pretty-printing and carried
            through to structured logs.
    """

    to: str
    subject: str
    html_body: str
    from_addr: str | None = None
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeliveryResult:
    """Outcome of a single ``backend.send()`` call.

    We intentionally do *not* raise on failure.  Email is a side-effect —
    a password-reset flow should not 500 just because SMTP is down.  The
    service layer logs the result and callers can branch on ``ok``.
    """

    ok: bool
    backend: str
    reason: str = ""  # Human-readable status ("sent", "smtp not configured", etc.)

    @classmethod
    def success(cls, backend: str, reason: str = "sent") -> DeliveryResult:
        return cls(ok=True, backend=backend, reason=reason)

    @classmethod
    def failure(cls, backend: str, reason: str) -> DeliveryResult:
        return cls(ok=False, backend=backend, reason=reason)


BackendName = Literal["console", "smtp", "noop", "memory"]


class EmailBackend(ABC):
    """Abstract transport for ``EmailMessage`` objects.

    Subclasses MUST be safe to call from an async context.  Blocking I/O
    (e.g. the SMTP handshake) belongs inside ``asyncio.to_thread`` so the
    event loop keeps serving requests.
    """

    #: Stable short name used in logs and ``DeliveryResult.backend``.
    name: BackendName

    @abstractmethod
    async def send(self, message: EmailMessage) -> DeliveryResult:
        """Deliver a single message. Never raises — return a DeliveryResult."""
        ...
