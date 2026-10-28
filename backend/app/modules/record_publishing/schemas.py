# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Record Publishing schemas - request/response for publish-and-distribute."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.file_transmittals.schemas import TransmittalReason

# The record kinds this module can publish. Extended as renderers are added
# (inspections next); the string values match the service registry keys.
RecordKind = Literal["daily_diary", "meeting"]


class PublishRecipientInput(BaseModel):
    """One explicit recipient supplied on the publish request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    display_name: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=32)


class PublishRecordRequest(BaseModel):
    """Publish a single project record as a PDF and distribute it.

    Recipients come from ``recipients`` and/or a saved ``distribution_list_id``;
    at least one resolved recipient is required. ``project_id`` is intentionally
    absent - it is resolved from the source record so a caller cannot publish
    into a project they do not own.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    source_kind: RecordKind
    source_id: UUID
    recipients: list[PublishRecipientInput] = Field(default_factory=list)
    distribution_list_id: UUID | None = None
    reason_code: TransmittalReason = "for_record"
    notes: str | None = Field(default=None, max_length=4000)
    # Preferred language for the rendered document; recorded now, honoured by
    # per-kind renderers as their localisation lands.
    locale: str | None = Field(default=None, max_length=12)


class PublishedRecipientOut(BaseModel):
    """One recipient in the publish result, with the links to forward."""

    email: str
    display_name: str | None = None
    role: str | None = None
    acknowledge_url: str | None = None
    record_url: str | None = None


class PublishRecordResponse(BaseModel):
    """Result of a publish-and-distribute action."""

    transmittal_id: UUID
    transmittal_number: str
    subject: str
    source_kind: str
    source_id: str
    project_id: UUID
    record_filename: str
    cover_sheet_path: str | None = None
    recipient_count: int
    recipients: list[PublishedRecipientOut]


class SupportedKindsResponse(BaseModel):
    """The record kinds that can currently be published."""

    kinds: list[str]
