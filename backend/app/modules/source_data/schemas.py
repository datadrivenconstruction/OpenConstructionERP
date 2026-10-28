# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the source-data (prerequisite documents) register."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Canonical vocabularies (open-ended; packs may extend via the DB) ───
#
# These are the built-in, jurisdiction-neutral document families. The DB column
# is a plain String so a regional pack can persist a value outside this list
# without a migration; the API validates against the union so the built-in UI
# pickers stay honest.

DOC_TYPES: tuple[str, ...] = (
    "permit",  # a permit / consent to build or operate
    "survey",  # a site or land survey
    "geotech",  # a geotechnical / soils report
    "tech_conditions",  # technical conditions from a utility / authority
    "title_deed",  # proof of land ownership / tenure
    "approval",  # a design / stage approval
    "technical_spec",  # a technical specification the delivery must meet
    "other",
)

DOCUMENT_STATUSES: tuple[str, ...] = (
    "requested",
    "received",
    "verified",
    "expiring_soon",
    "expired",
    "superseded",
)

# Statuses a caller may set explicitly; expiring_soon / expired are derived from
# the validity window and can never be set by hand.
_MANUAL_STATUSES: tuple[str, ...] = ("requested", "received", "verified", "superseded")

CHECKLIST_STATUSES: tuple[str, ...] = ("pending", "satisfied", "waived")

_DOC_TYPE_PATTERN = "^(" + "|".join(DOC_TYPES) + ")$"
_MANUAL_STATUS_PATTERN = "^(" + "|".join(_MANUAL_STATUSES) + ")$"
_CHECKLIST_STATUS_PATTERN = "^(" + "|".join(CHECKLIST_STATUSES) + ")$"


# ── Documents ──────────────────────────────────────────────────────────


class SourceDocumentCreate(BaseModel):
    """Body for ``POST /v1/source-data/documents``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    doc_type: str = Field(..., pattern=_DOC_TYPE_PATTERN)
    owner: str | None = Field(default=None, max_length=255)
    authority: str | None = Field(default=None, max_length=255)
    identifier: str | None = Field(default=None, max_length=120)
    issued_at: date | None = None
    valid_until: date | None = None
    shelf_life_days: int | None = Field(default=None, ge=0, le=36500)
    notify_days_before: int = Field(default=30, ge=0, le=365)
    blocks_schedule: bool = False
    superseded_by_id: UUID | None = None
    status: str | None = Field(
        default=None,
        pattern=_MANUAL_STATUS_PATTERN,
        description=(
            "Optional lifecycle status. Only requested / received / verified / "
            "superseded may be set; expiring_soon / expired are derived from the "
            "validity window. Defaults to requested."
        ),
    )
    notes: str = Field(default="", max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _dates_consistent(self) -> SourceDocumentCreate:
        if self.issued_at is not None and self.valid_until is not None and self.valid_until < self.issued_at:
            raise ValueError("valid_until must be on or after issued_at.")
        return self


class SourceDocumentUpdate(BaseModel):
    """Body for ``PATCH /v1/source-data/documents/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    doc_type: str | None = Field(default=None, pattern=_DOC_TYPE_PATTERN)
    owner: str | None = Field(default=None, max_length=255)
    authority: str | None = Field(default=None, max_length=255)
    identifier: str | None = Field(default=None, max_length=120)
    issued_at: date | None = None
    valid_until: date | None = None
    shelf_life_days: int | None = Field(default=None, ge=0, le=36500)
    notify_days_before: int | None = Field(default=None, ge=0, le=365)
    blocks_schedule: bool | None = None
    superseded_by_id: UUID | None = None
    status: str | None = Field(default=None, pattern=_MANUAL_STATUS_PATTERN)
    notes: str | None = Field(default=None, max_length=10000)
    metadata: dict[str, Any] | None = None


class SourceDocumentResponse(BaseModel):
    """Source document returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    doc_type: str
    owner: str | None = None
    authority: str | None = None
    identifier: str | None = None
    issued_at: date | None = None
    valid_until: date | None = None
    shelf_life_days: int | None = None
    notify_days_before: int = 30
    blocks_schedule: bool = False
    status: str = "requested"
    superseded_by_id: UUID | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
    )
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Computed convenience field. None when the document is perpetual (no
    # valid_until); otherwise signed - negative once expired.
    days_until_expiry: int | None = Field(
        default=None,
        description="Days to expiry: negative when expired, 0 on expiry day, None when perpetual.",
    )


# ── Checklist items ────────────────────────────────────────────────────


class SourceChecklistItemCreate(BaseModel):
    """Body for ``POST /v1/source-data/checklist``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    label: str = Field(..., min_length=1, max_length=255)
    required: bool = True
    doc_type: str | None = Field(default=None, pattern=_DOC_TYPE_PATTERN)
    satisfied_by_id: UUID | None = None
    status: str = Field(default="pending", pattern=_CHECKLIST_STATUS_PATTERN)


class SourceChecklistItemUpdate(BaseModel):
    """Body for ``PATCH /v1/source-data/checklist/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, min_length=1, max_length=255)
    required: bool | None = None
    doc_type: str | None = Field(default=None, pattern=_DOC_TYPE_PATTERN)
    satisfied_by_id: UUID | None = None
    status: str | None = Field(default=None, pattern=_CHECKLIST_STATUS_PATTERN)


class SourceChecklistItemResponse(BaseModel):
    """Checklist item returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    label: str
    required: bool = True
    doc_type: str | None = None
    satisfied_by_id: UUID | None = None
    status: str = "pending"
    created_at: datetime
    updated_at: datetime


# ── Aggregate payloads ─────────────────────────────────────────────────


class ChecklistSummary(BaseModel):
    """Completeness roll-up of a project's required source-data checklist."""

    total: int
    required: int
    satisfied: int
    waived: int
    pending: int
    complete: bool = Field(description="True when every required item is satisfied or waived.")
    missing_required: list[str] = Field(default_factory=list)


class DefectiveInputsNotice(BaseModel):
    """Structured payload for a "defective or missing source data" notice.

    Deliberately *data*, not prose - another module (correspondence) turns this
    into a letter. This module never renders one.
    """

    project_id: UUID
    recipient: str | None = Field(
        default=None,
        description="Owner responsible for the largest share of the outstanding items, when derivable.",
    )
    missing_items: list[str] = Field(default_factory=list)
    expired_documents: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    has_defects: bool = False


__all__ = [
    "CHECKLIST_STATUSES",
    "DOCUMENT_STATUSES",
    "DOC_TYPES",
    "ChecklistSummary",
    "DefectiveInputsNotice",
    "SourceChecklistItemCreate",
    "SourceChecklistItemResponse",
    "SourceChecklistItemUpdate",
    "SourceDocumentCreate",
    "SourceDocumentResponse",
    "SourceDocumentUpdate",
]
