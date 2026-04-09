"""Correspondence Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CorrespondenceCreate(BaseModel):
    """Create a new correspondence record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    direction: str = Field(..., pattern=r"^(incoming|outgoing)$")
    subject: str = Field(..., min_length=1, max_length=500)
    from_contact_id: str | None = None
    to_contact_ids: list[str] = Field(default_factory=list)
    date_sent: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_received: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    correspondence_type: str = Field(
        ...,
        pattern=r"^(letter|email|notice|memo)$",
    )
    linked_document_ids: list[str] = Field(default_factory=list)
    linked_transmittal_id: str | None = None
    linked_rfi_id: str | None = None
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CorrespondenceUpdate(BaseModel):
    """Partial update for a correspondence record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    direction: str | None = Field(default=None, pattern=r"^(incoming|outgoing)$")
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    from_contact_id: str | None = None
    to_contact_ids: list[str] | None = None
    date_sent: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_received: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    correspondence_type: str | None = Field(
        default=None,
        pattern=r"^(letter|email|notice|memo)$",
    )
    linked_document_ids: list[str] | None = None
    linked_transmittal_id: str | None = None
    linked_rfi_id: str | None = None
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class CorrespondenceResponse(BaseModel):
    """Correspondence returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    reference_number: str
    direction: str
    subject: str
    from_contact_id: str | None = None
    to_contact_ids: list[str] = Field(default_factory=list)
    date_sent: str | None = None
    date_received: str | None = None
    correspondence_type: str
    linked_document_ids: list[str] = Field(default_factory=list)
    linked_transmittal_id: str | None = None
    linked_rfi_id: str | None = None
    notes: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
