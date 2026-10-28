# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the inbound capture API.

The request bodies stay deliberately permissive: the pure
:mod:`~app.modules.inbound_capture.normalize` engine already tolerates missing /
oddly-named fields and maps each channel's ad-hoc payload onto one canonical
shape, so the schemas accept an open ``payload`` dict (the already-parsed email
headers / body, or the provider's webhook / SMS JSON) rather than re-declaring
every channel's field set here. The response mirrors the normalized
:class:`~app.modules.inbound_capture.normalize.InboundMessage` plus the id of the
correspondence row it was persisted as, so a caller can confirm what was stored
and follow the link into the Correspondence module.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InboundEmailRequest(BaseModel):
    """An already-parsed inbound email to capture against a project.

    The upstream mail step has already done the MIME parsing; ``payload`` is the
    resulting header / body dict (``from`` / ``to`` / ``subject`` / ``text`` /
    ``message_id`` / ``attachments`` etc.). The normalizer picks the fields it
    recognises and breadcrumbs the rest, so an unfamiliar provider shape is
    captured rather than rejected.
    """

    project_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class InboundWebhookRequest(BaseModel):
    """A provider chat / SMS webhook delivery to capture against a project.

    ``payload`` is the provider's raw JSON body (already parsed). The ``channel``
    hint lets the caller record the concrete channel the provider speaks
    (``sms`` / ``webhook`` / a named chat channel); when omitted the gateway
    infers it from the ``{provider}`` path segment. Signature verification is
    performed by the router against the RAW request body before this typed model
    is ever trusted - see the router's verification seam.
    """

    project_id: str
    channel: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class InboundAttachmentOut(BaseModel):
    """One captured attachment pointer (never the bytes themselves)."""

    filename: str
    content_type: str
    size_bytes: int
    storage_hint: str | None


class InboundMessageOut(BaseModel):
    """A captured inbound message and the correspondence row it became.

    ``correspondence_id`` is the persisted ``oe_correspondence`` row;
    ``reference_number`` is that row's human reference (``COR-007``).
    ``deduplicated`` is true when this delivery matched an already-captured
    message (same channel + external id) and the existing row was returned
    instead of a new one being created - the idempotency contract made visible
    to the caller. ``external_message_id`` is the provider's own id (the
    idempotency anchor); ``idempotency_key`` is the engine's stable digest of
    ``(channel, external id)``.
    """

    correspondence_id: str
    project_id: str
    reference_number: str
    channel: str
    external_message_id: str
    idempotency_key: str
    direction: str
    sender: str
    recipients: list[str]
    sent_at: str
    subject: str
    body: str
    in_reply_to: str | None
    attachments: list[InboundAttachmentOut]
    raw_refs: list[str]
    deduplicated: bool


class InboundCapturedList(BaseModel):
    """A page of a project's captured inbound messages, newest first.

    ``items`` are the captured rows projected to the read shape (each carries
    ``deduplicated = false`` here - the flag is only meaningful at capture time,
    not when listing what is already stored). ``total`` is the count of captured
    messages for the project, so the UI can page without re-counting.
    """

    items: list[InboundMessageOut]
    total: int
