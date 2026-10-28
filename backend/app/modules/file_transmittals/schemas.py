# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Transmittals (W7) Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Mirrors models.TRANSMITTAL_REASONS / TRANSMITTAL_STATUSES; duplicated
# as ``Literal`` here so OpenAPI surfaces the allowed values.
TransmittalReason = Literal[
    "for_review",
    "for_construction",
    "for_approval",
    "for_information",
    "for_record",
]

TransmittalStatus = Literal[
    "draft",
    "sent",
    "acknowledged",
    "rejected",
]

FileKindLiteral = Literal[
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
]


class TransmittalItemCreate(BaseModel):
    """Add one file to a transmittal (draft or sent)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file_kind: FileKindLiteral
    file_id: str = Field(min_length=1, max_length=64)
    canonical_name_snapshot: str = Field(min_length=1, max_length=512)
    file_version_snapshot: str | None = Field(default=None, max_length=32)
    sort_order: int = Field(default=0, ge=0)


class TransmittalItemResponse(BaseModel):
    """One file row in a transmittal."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transmittal_id: UUID
    file_kind: str
    file_id: str
    file_version_snapshot: str | None
    canonical_name_snapshot: str
    sort_order: int


class TransmittalRecipientCreate(BaseModel):
    """Add one recipient (no auth-side identity required)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    display_name: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=32)


class TransmittalRecipientResponse(BaseModel):
    """One recipient + ack state."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transmittal_id: UUID
    email: str
    display_name: str | None
    role: str | None
    acknowledged_at: datetime | None
    # Token is exposed only on the response from the send endpoint -
    # listing transmittals returns ``None`` so a viewer cannot harvest
    # tokens server-side. Service is responsible for masking.
    acknowledge_token: str | None


class TransmittalCreate(BaseModel):
    """Create a new draft transmittal.

    Items + recipients can be added during creation OR with the separate
    ``POST /{id}/items`` / ``POST /{id}/recipients`` endpoints. Sending
    is a separate, idempotent step (``POST /{id}/send/``).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    subject: str = Field(min_length=1, max_length=255)
    reason_code: TransmittalReason
    notes: str | None = Field(default=None, max_length=4000)
    items: list[TransmittalItemCreate] = Field(default_factory=list)
    recipients: list[TransmittalRecipientCreate] = Field(default_factory=list)


class TransmittalResponse(BaseModel):
    """Full transmittal payload (header + items + recipients)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    number: str
    subject: str
    reason_code: str
    sender_id: UUID | None
    sent_at: datetime
    status: str
    notes: str | None
    cover_sheet_path: str | None
    items: list[TransmittalItemResponse]
    recipients: list[TransmittalRecipientResponse]
    created_at: datetime
    updated_at: datetime


class TransmittalListItem(BaseModel):
    """Compact row for the log page; omits items + recipients arrays."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    number: str
    subject: str
    reason_code: str
    sender_id: UUID | None
    sent_at: datetime
    status: str
    item_count: int
    recipient_count: int
    acknowledged_count: int
    created_at: datetime
    updated_at: datetime


class TransmittalAcknowledgeResponse(BaseModel):
    """Public ack endpoint response."""

    transmittal_number: str
    subject: str
    acknowledged_at: datetime
    recipient_email: str
