# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Transmittals Pydantic schemas - request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.transmittals.logic import PURPOSE_CODES, response_due_error

# ISO 8601 (YYYY-MM-DD) is the one calendar-date format that is unambiguous in
# every country, so both date fields accept it and nothing else.
_ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
# Build the purpose-code pattern from the single source of truth in logic.py so
# the two can never drift apart.
_PURPOSE_PATTERN = r"^(" + "|".join(PURPOSE_CODES) + r")$"
_PURPOSE_HELP = (
    "Why the documents are being sent: "
    "for_approval, for_review, for_information, for_construction, for_tender or for_record."
)

# ── Recipients ──────────────────────────────────────────────────────────


class RecipientCreate(BaseModel):
    """Add a recipient to a transmittal.

    A recipient can be named by free text (``recipient_name`` / ``recipient_email``
    for an external party), by a stored contact (``recipient_org_id``) or by a
    system user (``recipient_user_id``). Any combination is accepted, including a
    bare row, so a draft can be built up incrementally.
    """

    recipient_org_id: UUID | None = None
    recipient_user_id: UUID | None = None
    recipient_name: str | None = Field(default=None, max_length=200)
    recipient_email: str | None = Field(default=None, max_length=320)
    action_required: str | None = Field(default=None, max_length=100)

    @field_validator("recipient_name", "recipient_email", "action_required")
    @classmethod
    def _sanitise_text(cls, value: str | None) -> str | None:
        """Strip control characters and surrounding whitespace.

        A recipient name or email may later be printed on a cover sheet or used
        in a notification, so a newline or other control character must never
        survive to enable header injection. An empty result collapses to None.
        """
        if value is None:
            return None
        cleaned = "".join(ch for ch in value if ch == " " or ch.isprintable()).strip()
        return cleaned or None


class RecipientResponse(BaseModel):
    """Recipient in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    transmittal_id: UUID
    recipient_org_id: UUID | None = None
    recipient_user_id: UUID | None = None
    recipient_name: str | None = None
    recipient_email: str | None = None
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
    revision_id: UUID | None = None
    item_number: int = Field(..., ge=1)
    description: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=5000)


class ItemResponse(BaseModel):
    """Item in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    transmittal_id: UUID
    document_id: UUID | None = None
    revision_id: UUID | None = None
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
    purpose_code: str = Field(..., pattern=_PURPOSE_PATTERN, description=_PURPOSE_HELP)
    issued_date: str | None = Field(
        default=None,
        pattern=_ISO_DATE_PATTERN,
        max_length=20,
        description="Date the transmittal is sent, as YYYY-MM-DD.",
    )
    response_due_date: str | None = Field(
        default=None,
        pattern=_ISO_DATE_PATTERN,
        max_length=20,
        description="Date a response is expected by, as YYYY-MM-DD. Cannot be before the issue date.",
    )
    cover_note: str | None = Field(default=None, max_length=5000)
    recipients: list[RecipientCreate] = Field(default_factory=list)
    items: list[ItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_response_due_date(self) -> "TransmittalCreate":
        error = response_due_error(self.issued_date, self.response_due_date)
        if error is not None:
            raise ValueError(error)
        return self


class TransmittalUpdate(BaseModel):
    """Partial update for a transmittal. Allowed only while it is still a draft."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str | None = Field(default=None, min_length=1, max_length=500)
    sender_org_id: UUID | None = None
    purpose_code: str | None = Field(default=None, pattern=_PURPOSE_PATTERN, description=_PURPOSE_HELP)
    issued_date: str | None = Field(
        default=None,
        pattern=_ISO_DATE_PATTERN,
        max_length=20,
        description="Date the transmittal is sent, as YYYY-MM-DD.",
    )
    response_due_date: str | None = Field(
        default=None,
        pattern=_ISO_DATE_PATTERN,
        max_length=20,
        description="Date a response is expected by, as YYYY-MM-DD. Cannot be before the issue date.",
    )
    cover_note: str | None = Field(default=None, max_length=5000)
    recipients: list[RecipientCreate] | None = None
    items: list[ItemCreate] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_response_due_date(self) -> "TransmittalUpdate":
        # Only checkable when both dates are supplied in the same request; the
        # service layer covers the case where only one date changes.
        error = response_due_error(self.issued_date, self.response_due_date)
        if error is not None:
            raise ValueError(error)
        return self


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
    status: str = Field(
        description="draft (being prepared), issued (sent and locked) or responded (all recipients replied).",
    )
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
