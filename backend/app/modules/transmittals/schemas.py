"""Transmittals Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Recipients ──────────────────────────────────────────────────────────


class RecipientCreate(BaseModel):
    """Add a recipient to a transmittal."""

    recipient_org_id: UUID | None = None
    recipient_user_id: UUID | None = None
    action_required: str | None = Field(default=None, max_length=100)


class RecipientResponse(BaseModel):
    """Recipient in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    transmittal_id: UUID
    recipient_org_id: UUID | None = None
    recipient_user_id: UUID | None = None
    action_required: str | None = None
    acknowledged_at: datetime | None = None
    response: str | None = None
    responded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── Items ───────────────────────────────────────────────────────────────


class ItemCreate(BaseModel):
    """Add a line item to a transmittal."""

    document_id: UUID | None = None
    item_number: int = Field(..., ge=1)
    description: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=5000)


class ItemResponse(BaseModel):
    """Item in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    transmittal_id: UUID
    document_id: UUID | None = None
    item_number: int
    description: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Transmittal Create / Update ─────────────────────────────────────────


class TransmittalCreate(BaseModel):
    """Create a new transmittal."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    subject: str = Field(..., min_length=1, max_length=500)
    sender_org_id: UUID | None = None
    purpose_code: str = Field(
        ...,
        pattern=r"^(for_approval|for_information|for_construction|for_tender|for_review|for_record)$",
    )
    issued_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    cover_note: str | None = Field(default=None, max_length=5000)
    recipients: list[RecipientCreate] = Field(default_factory=list)
    items: list[ItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransmittalUpdate(BaseModel):
    """Partial update for a transmittal (only while unlocked)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str | None = Field(default=None, min_length=1, max_length=500)
    sender_org_id: UUID | None = None
    purpose_code: str | None = Field(
        default=None,
        pattern=r"^(for_approval|for_information|for_construction|for_tender|for_review|for_record)$",
    )
    issued_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    cover_note: str | None = Field(default=None, max_length=5000)
    recipients: list[RecipientCreate] | None = None
    items: list[ItemCreate] | None = None
    metadata: dict[str, Any] | None = None


# ── Response ────────────────────────────────────────────────────────────


class TransmittalResponse(BaseModel):
    """Transmittal returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    transmittal_number: str
    subject: str
    sender_org_id: UUID | None = None
    purpose_code: str
    issued_date: str | None = None
    response_due_date: str | None = None
    status: str
    cover_note: str | None = None
    is_locked: bool
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    recipients: list[RecipientResponse] = Field(default_factory=list)
    items: list[ItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TransmittalListResponse(BaseModel):
    """Paginated list of transmittals."""

    items: list[TransmittalResponse]
    total: int
    offset: int
    limit: int


# ── Acknowledge / Respond ───────────────────────────────────────────────


class AcknowledgeRequest(BaseModel):
    """Acknowledge receipt of a transmittal (empty body is fine)."""

    pass


class RespondRequest(BaseModel):
    """Submit a response to a transmittal."""

    response: str = Field(..., min_length=1, max_length=5000)
