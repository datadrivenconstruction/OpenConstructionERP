# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Store webhook: verify the delivery, parse it, record it exactly once.

Payment happens at an external checkout run by a merchant of record, which
also handles VAT worldwide. The platform keeps no billing of its own: the
store calls this webhook when an order is paid, and the webhook grants the
course through :mod:`app.modules.trainer.provisioning`.

Intended route (Wave 2 owns the router)::

    POST /api/v1/trainer/webhook/
        public (no session cookie, no bearer token), authenticated by HMAC
        raw request body in, ``WebhookOutcome.http_status`` and
        ``WebhookOutcome.body()`` out

The router must pass the RAW body bytes (``await request.body()``), never a
re-serialised JSON document, and should put the per-IP rate limiter in front
of this function: a rejected delivery writes one log row.

Signature scheme (generic adapter)
----------------------------------
The store sends two headers:

* ``X-OE-Timestamp``: Unix time in whole seconds, as decimal digits.
* ``X-OE-Signature``: ``sha256=<hex>`` or bare ``<hex>``, the HMAC-SHA256 of
  ``<timestamp> + "." + <raw body bytes>`` keyed with
  ``Settings.trainer_webhook_secret``.

The timestamp is inside the signed message. Signing the body alone would let
anyone who captured one delivery replay it later under a fresh timestamp
header, and the replay window would protect nothing. A delivery older or
newer than :data:`REPLAY_WINDOW_SECONDS` is refused; a replay inside the
window carries an ``event_id`` that is already recorded and is answered as a
duplicate without writing anything.

Provider seam
-------------
Everything provider-specific sits in one :class:`ProviderAdapter`: the two
header names, how the signed message is built and how a payload maps to
:class:`OrderPaid`. Supporting a specific merchant of record later means one
new file that builds an adapter and registers it in :data:`ADAPTERS`.

Outcomes
--------
* flag off: 404 ``disabled``. Nothing is verified, read or written.
* no secret configured: 503 ``not_configured``, nothing written.
* bad, missing, malformed or stale signature: 401 ``rejected``. One log row
  is written with ``signature_ok=False``, no payload, no email, and a
  synthetic event id, so a forged delivery can never claim the id of a real
  one and turn it into a duplicate.
* signed but unreadable payload: 400 ``invalid``.
* already recorded event: 200 ``duplicate`` with the stored outcome; nothing
  is written again. A stored ``failed`` event is the exception: a resend
  retries it.
* unknown event type: 200 ``ignored``, recorded once, so the store stops
  retrying.
* ``order.paid``: 200 ``processed`` (or ``ignored`` / ``failed`` from
  provisioning, still 200, because a store retry cannot fix an unknown offer
  or a seed bug). An unexpected exception answers 500 ``failed`` and the
  store's resend retries it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.trainer.models import TrainerWebhookEvent
from app.modules.trainer.provisioning import (
    ProvisioningResult,
    SeedOnEnrol,
    complete_provisioning,
    provision_order_paid,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.core.email import EmailService

logger = logging.getLogger(__name__)

#: A delivery whose timestamp is further than this from the server clock, in
#: either direction, is refused.
REPLAY_WINDOW_SECONDS = 300

#: The only event type that grants anything.
ORDER_PAID = "order.paid"

#: The adapter used when the router names none.
DEFAULT_PROVIDER = "generic"

_HEX_SIGNATURE_RE = re.compile(r"^(?:sha256=)?([0-9a-fA-F]{64})$")
_TIMESTAMP_RE = re.compile(r"^[0-9]{1,12}$")
_MAX_ERROR_CHARS = 500


# ── The paid order ───────────────────────────────────────────────────────────


class OrderPaid(BaseModel):
    """A paid order, in the platform's words, whatever store sent it.

    ``offer_code`` is the store's product reference; ``oe_trainer_offer``
    maps it to one or more course keys. ``order_ref`` is optional and only
    kept for the admin screens.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=128)
    offer_code: str = Field(min_length=1, max_length=128)
    email: EmailStr
    name: str = Field(default="", max_length=255)
    locale: str | None = Field(default=None, max_length=16)
    paid_at: AwareDatetime
    order_ref: str | None = Field(default=None, max_length=128)

    @field_validator("email")
    @classmethod
    def _lowercase_email(cls, value: str) -> str:
        return value.lower()


@dataclass(frozen=True)
class ProviderEvent:
    """One verified delivery after the adapter read it.

    ``order`` is set only for ``order.paid``. ``payload`` is the delivery with
    address, phone, card and tax fields removed; it is what gets stored.
    """

    event_id: str
    event_type: str
    payload: dict[str, Any]
    order: OrderPaid | None = None


class PayloadError(ValueError):
    """A signed delivery the adapter cannot read.

    ``event_id`` and ``event_type`` are whatever could be read before the
    failure, so the delivery can still be recorded. ``reason`` never carries
    a submitted value, only field names, so it is safe to log and store.
    """

    def __init__(self, reason: str, *, event_id: str | None = None, event_type: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.event_id = event_id
        self.event_type = event_type


# ── PII removal ──────────────────────────────────────────────────────────────

#: A payload key is dropped when any of its word parts is one of these.
#: Matching whole parts, not substrings, keeps ``company`` (``pan``) and
#: ``description`` (``ip``) while dropping ``billingAddress`` and ``tax_id``.
_PII_KEY_PARTS = frozenset(
    {
        "address",
        "street",
        "city",
        "postcode",
        "postal",
        "zip",
        "phone",
        "mobile",
        "card",
        "pan",
        "cvc",
        "cvv",
        "iban",
        "bic",
        "tax",
        "vat",
        "billing",
        "shipping",
        "ip",
    }
)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_KEY_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def _key_parts(key: str) -> set[str]:
    spaced = _CAMEL_RE.sub("_", key)
    return {part.lower() for part in _KEY_SPLIT_RE.split(spaced) if part}


def redact_payload(value: Any) -> Any:
    """Return ``value`` with every address, phone, card and tax field removed.

    The buyer's email and name stay: provisioning needs them, and the admin
    screen shows who an event was for.
    """
    if isinstance(value, Mapping):
        return {
            str(key): redact_payload(item) for key, item in value.items() if not (_key_parts(str(key)) & _PII_KEY_PARTS)
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


# ── The provider seam ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderAdapter:
    """Everything that differs between stores, in one place.

    Attributes:
        name: Stored in ``oe_trainer_webhook_event.provider`` and matched
            against ``oe_trainer_offer.provider``.
        signature_header: Lower-case header carrying the signature.
        timestamp_header: Lower-case header carrying the Unix timestamp.
        signed_message: Builds the bytes the store signed, from the raw body
            and the timestamp header exactly as received.
        parse: Maps a decoded JSON payload to a :class:`ProviderEvent`.
    """

    name: str
    signature_header: str
    timestamp_header: str
    signed_message: Callable[[bytes, str], bytes]
    parse: Callable[[Any], ProviderEvent]


def _generic_signed_message(raw_body: bytes, timestamp: str) -> bytes:
    return timestamp.encode("ascii") + b"." + raw_body


_ORDER_FIELDS = ("offer_code", "order_ref", "email", "name", "locale", "paid_at")


def parse_generic_payload(payload: Any) -> ProviderEvent:
    """Map the generic JSON shape to a :class:`ProviderEvent`.

    Shape::

        {"id": "evt_...", "type": "order.paid",
         "data": {"offer_code": "...", "order_ref": "...", "email": "...",
                  "name": "...", "locale": "de", "paid_at": "2026-10-05T10:00:00Z"}}

    Keys in ``data`` other than the six above are ignored (a store sends
    amounts, currency and its own ids); they are kept in the stored payload
    unless they are personal data.

    Raises:
        PayloadError: the payload is not this shape. The message names
            fields, never values.
    """
    if not isinstance(payload, Mapping):
        raise PayloadError("payload is not a JSON object")
    event_id = payload.get("id")
    event_type = payload.get("type")
    if not isinstance(event_id, str) or not 1 <= len(event_id.strip()) <= 128:
        raise PayloadError("missing or invalid field: id")
    event_id = event_id.strip()
    if not isinstance(event_type, str) or not 1 <= len(event_type.strip()) <= 64:
        raise PayloadError("missing or invalid field: type", event_id=event_id)
    event_type = event_type.strip()
    redacted = redact_payload(payload)
    if event_type != ORDER_PAID:
        return ProviderEvent(event_id=event_id, event_type=event_type, payload=redacted)

    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise PayloadError("missing or invalid field: data", event_id=event_id, event_type=event_type)
    fields = {key: data[key] for key in _ORDER_FIELDS if data.get(key) is not None}
    try:
        order = OrderPaid.model_validate({"event_id": event_id, **fields})
    except ValidationError as exc:
        names = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
        # ``from None``: the ValidationError repeats the submitted values.
        raise PayloadError(
            f"missing or invalid fields: {', '.join(names) or 'data'}",
            event_id=event_id,
            event_type=event_type,
        ) from None
    return ProviderEvent(event_id=event_id, event_type=event_type, payload=redacted, order=order)


GENERIC_ADAPTER = ProviderAdapter(
    name=DEFAULT_PROVIDER,
    signature_header="x-oe-signature",
    timestamp_header="x-oe-timestamp",
    signed_message=_generic_signed_message,
    parse=parse_generic_payload,
)

#: Registered stores. A merchant-of-record adapter adds one entry.
ADAPTERS: dict[str, ProviderAdapter] = {GENERIC_ADAPTER.name: GENERIC_ADAPTER}


# ── Verification ─────────────────────────────────────────────────────────────


class VerifyFailure(StrEnum):
    """Why a delivery was refused. The values are stored and logged."""

    MISSING_SIGNATURE = "missing_signature"
    MALFORMED_SIGNATURE = "malformed_signature"
    MISSING_TIMESTAMP = "missing_timestamp"
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    BAD_SIGNATURE = "bad_signature"
    STALE_TIMESTAMP = "stale_timestamp"


def compute_signature(secret: str, raw_body: bytes, timestamp: str, adapter: ProviderAdapter = GENERIC_ADAPTER) -> str:
    """The hex HMAC-SHA256 a store would send for ``raw_body`` at ``timestamp``."""
    message = adapter.signed_message(raw_body, timestamp)
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _lower_keys(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): value for key, value in headers.items()}


def verify_delivery(
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    now: float,
    adapter: ProviderAdapter = GENERIC_ADAPTER,
) -> VerifyFailure | None:
    """Check the signature over the raw body and the replay window.

    Returns None when the delivery is authentic and fresh, else the reason.
    The comparison is :func:`hmac.compare_digest` over ASCII bytes; a header
    that is not a 64-digit hex string is refused before any comparison, so a
    non-ASCII header is a 401 and never a ``TypeError``.
    """
    lowered = _lower_keys(headers)
    presented = (lowered.get(adapter.signature_header) or "").strip()
    timestamp = (lowered.get(adapter.timestamp_header) or "").strip()
    if not presented:
        return VerifyFailure.MISSING_SIGNATURE
    if not timestamp:
        return VerifyFailure.MISSING_TIMESTAMP
    match = _HEX_SIGNATURE_RE.match(presented)
    if match is None:
        return VerifyFailure.MALFORMED_SIGNATURE
    if _TIMESTAMP_RE.match(timestamp) is None:
        return VerifyFailure.MALFORMED_TIMESTAMP
    expected = compute_signature(secret, raw_body, timestamp, adapter)
    if not hmac.compare_digest(expected.encode("ascii"), match.group(1).lower().encode("ascii")):
        return VerifyFailure.BAD_SIGNATURE
    if abs(now - int(timestamp)) > REPLAY_WINDOW_SECONDS:
        return VerifyFailure.STALE_TIMESTAMP
    return None


# ── The handler ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WebhookOutcome:
    """What the router answers.

    ``status`` is one of ``processed``, ``duplicate``, ``ignored``,
    ``failed``, ``rejected``, ``invalid``, ``disabled``, ``not_configured``.
    ``stored_status`` is set on a duplicate: the outcome recorded the first
    time.
    """

    http_status: int
    status: str
    event_id: str | None = None
    stored_status: str | None = None
    user_id: uuid.UUID | None = None
    enrolment_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)

    def body(self) -> dict[str, str]:
        """The JSON body the store sees. It carries no ids and no personal data."""
        out = {"status": self.status}
        if self.stored_status is not None:
            out["outcome"] = self.stored_status
        return out


def _secret_value(settings: Settings) -> str:
    secret = settings.trainer_webhook_secret
    if secret is None:
        return ""
    return secret.get_secret_value()


def _clip(text: str) -> str:
    return text[:_MAX_ERROR_CHARS]


async def _record_rejected(session: AsyncSession, provider: str, failure: VerifyFailure, raw_body: bytes) -> None:
    """Log a refused delivery without trusting anything in it."""
    session.add(
        TrainerWebhookEvent(
            provider=provider,
            # Never the body's id: a forged delivery must not be able to
            # occupy the id of a real one.
            event_id=f"rejected:{uuid.uuid4().hex}",
            event_type="unverified",
            signature_ok=False,
            status="failed",
            payload_sha256=hashlib.sha256(raw_body).hexdigest(),
            payload=None,
            email=None,
            error=failure.value,
            processed_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def _claim(
    session: AsyncSession,
    provider: str,
    event: ProviderEvent,
    raw_body: bytes,
) -> tuple[TrainerWebhookEvent, TrainerWebhookEvent | None]:
    """Insert the event row, or find the one already there.

    Returns ``(row, None)`` when this delivery owns the event and should
    process it (a fresh row, or a stored ``failed`` row being retried), and
    ``(existing, existing)`` for a duplicate.
    """
    order = event.order
    row = TrainerWebhookEvent(
        provider=provider,
        event_id=event.event_id,
        event_type=event.event_type,
        signature_ok=True,
        status="received",
        email=order.email if order else None,
        product_ref=order.offer_code if order else None,
        order_ref=order.order_ref if order else None,
        payload_sha256=hashlib.sha256(raw_body).hexdigest(),
        payload=event.payload,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        pass
    else:
        return row, None

    # The unique (provider, event_id) pair is taken. Lock the stored row so
    # two concurrent resends of a failed event do not both retry it.
    existing = (
        await session.execute(
            select(TrainerWebhookEvent)
            .where(
                TrainerWebhookEvent.provider == provider,
                TrainerWebhookEvent.event_id == event.event_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    if existing.status == "failed" and existing.signature_ok:
        existing.status = "received"
        existing.error = None
        existing.payload_sha256 = row.payload_sha256
        existing.payload = event.payload
        await session.flush()
        return existing, None
    return existing, existing


async def handle_webhook(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    seed_on_enrol: SeedOnEnrol,
    provider: str = DEFAULT_PROVIDER,
    email_service: EmailService | None = None,
    now: float | None = None,
) -> WebhookOutcome:
    """Verify, record and act on one store delivery.

    This function owns its transaction boundaries: it commits the event row
    together with the provisioning writes, then seeds and mails after the
    commit (the seeder opens its own session and must see the enrolment).

    Args:
        session: The request session.
        settings: Application settings; ``academy_mode`` and
            ``trainer_webhook_secret`` are read from it.
        raw_body: The request body exactly as received.
        headers: The request headers (any mapping; names are matched
            case-insensitively).
        seed_on_enrol: Stream C's seeder entry point for seed stage S0.
        provider: Key into :data:`ADAPTERS`.
        email_service: Mail service; the platform's shared one when None.
        now: Unix time for the replay window; the wall clock when None.

    Returns:
        The outcome for the router to answer with.
    """
    if not settings.academy_mode:
        return WebhookOutcome(http_status=404, status="disabled")

    secret = _secret_value(settings)
    if not secret:
        logger.warning("Trainer webhook refused a delivery: no webhook secret is configured")
        return WebhookOutcome(http_status=503, status="not_configured")

    adapter = ADAPTERS.get(provider)
    if adapter is None:
        logger.warning("Trainer webhook refused a delivery: unknown provider %r", provider)
        return WebhookOutcome(http_status=404, status="disabled")

    failure = verify_delivery(raw_body, headers, secret, now=time.time() if now is None else now, adapter=adapter)
    if failure is not None:
        logger.warning("Trainer webhook rejected a delivery from %s: %s", adapter.name, failure.value)
        await _record_rejected(session, adapter.name, failure, raw_body)
        return WebhookOutcome(http_status=401, status="rejected")

    try:
        decoded = json.loads(raw_body)
    except ValueError:
        logger.warning("Trainer webhook got a signed delivery from %s that is not JSON", adapter.name)
        return WebhookOutcome(http_status=400, status="invalid")
    try:
        event = adapter.parse(decoded)
    except PayloadError as exc:
        logger.warning("Trainer webhook got an unreadable delivery from %s: %s", adapter.name, exc.reason)
        if exc.event_id is None:
            return WebhookOutcome(http_status=400, status="invalid")
        bare = ProviderEvent(
            event_id=exc.event_id,
            event_type=exc.event_type or "unknown",
            payload=redact_payload(decoded),
        )
        row, duplicate = await _claim(session, adapter.name, bare, raw_body)
        if duplicate is not None:
            return WebhookOutcome(200, "duplicate", event_id=bare.event_id, stored_status=duplicate.status)
        row.status = "failed"
        row.error = _clip(f"invalid_payload: {exc.reason}")
        row.processed_at = datetime.now(UTC)
        await session.commit()
        return WebhookOutcome(http_status=400, status="invalid", event_id=bare.event_id)

    row, duplicate = await _claim(session, adapter.name, event, raw_body)
    if duplicate is not None:
        logger.info("Trainer webhook event %s from %s is a duplicate", event.event_id, adapter.name)
        await session.commit()
        return WebhookOutcome(
            http_status=200,
            status="duplicate",
            event_id=event.event_id,
            stored_status=duplicate.status,
            user_id=duplicate.user_id,
            enrolment_ids=(duplicate.enrolment_id,) if duplicate.enrolment_id else (),
        )

    if event.event_type != ORDER_PAID or event.order is None:
        row.status = "ignored"
        row.error = "unhandled_event_type"
        row.processed_at = datetime.now(UTC)
        await session.commit()
        logger.info("Trainer webhook ignored event %s of type %r", event.event_id, event.event_type)
        return WebhookOutcome(http_status=200, status="ignored", event_id=event.event_id)

    try:
        async with session.begin_nested():
            result = await provision_order_paid(session, settings, event.order, provider=adapter.name)
    except Exception as exc:
        # The provisioning savepoint is rolled back; the event row stays and
        # is marked failed, so the store's resend retries it.
        logger.exception("Trainer provisioning crashed for event %s", event.event_id)
        row.status = "failed"
        row.error = _clip(f"error: {type(exc).__name__}")
        row.processed_at = datetime.now(UTC)
        await session.commit()
        return WebhookOutcome(http_status=500, status="failed", event_id=event.event_id)

    _apply_result(row, result)
    await session.commit()

    if result.needs_completion:
        result = await complete_provisioning(
            session,
            settings,
            result,
            seed_on_enrol=seed_on_enrol,
            email_service=email_service,
        )
        if result.seed_failures:
            row.status = "failed"
            row.error = _clip("seed_failed: " + ", ".join(str(eid) for eid in result.seed_failures))
            await session.commit()

    return WebhookOutcome(
        http_status=200,
        status=row.status,
        event_id=event.event_id,
        user_id=result.user_id,
        enrolment_ids=tuple(item.enrolment_id for item in result.enrolments),
    )


def _apply_result(row: TrainerWebhookEvent, result: ProvisioningResult) -> None:
    row.status = result.status
    row.error = _clip(result.error) if result.error else None
    row.user_id = result.user_id
    row.enrolment_id = result.enrolments[0].enrolment_id if result.enrolments else None
    row.processed_at = datetime.now(UTC)
