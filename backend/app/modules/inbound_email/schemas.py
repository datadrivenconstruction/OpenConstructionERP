# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic response schemas for the inbound email API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EmailAttachmentOut(BaseModel):
    """Metadata for one message attachment."""

    model_config = ConfigDict(from_attributes=True)

    filename: str
    content_type: str
    size_bytes: int


class ParsedEmailOut(BaseModel):
    """Normalized view of a parsed stored message."""

    model_config = ConfigDict(from_attributes=True)

    message_id: str | None
    subject: str
    from_addr: str
    to_addrs: list[str]
    cc_addrs: list[str]
    date_iso: str | None
    in_reply_to: str | None
    references: list[str]
    body_text: str
    attachments: list[EmailAttachmentOut]


class DelaySignalOut(BaseModel):
    """One detected delay category with its evidence and suggested fragnet."""

    model_config = ConfigDict(from_attributes=True)

    category: str
    confidence: float
    matched_phrases: list[str]
    suggested_activities: list[str]


class InboundEmailAnalysisOut(BaseModel):
    """A parsed message plus any delay signals detected within it."""

    model_config = ConfigDict(from_attributes=True)

    email: ParsedEmailOut
    delay_signals: list[DelaySignalOut]
