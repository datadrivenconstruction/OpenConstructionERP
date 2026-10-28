# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas and canonical vocabularies for the review-authority module.

The vocabularies below are the built-in, jurisdiction-neutral code sets. The DB
columns are plain ``String`` so a regional pack can persist a value outside
these lists without a migration; the API validates against the union so the
built-in UI pickers stay honest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Vocabularies ───────────────────────────────────────────────────────

AUTHORITY_KINDS: tuple[str, ...] = (
    "state_expertise",  # RU-style state expertise (Главгосэкспертиза and peers)
    "building_control",  # UK-style building control body
    "ahj",  # US-style authority having jurisdiction
    "technical_review",  # an internal / third-party technical review board
    "other",
)

# Cycle FSM statuses.
CYCLE_STATUSES: tuple[str, ...] = (
    "draft",
    "submitted",
    "under_review",
    "remarks_issued",
    "responding",
    "resubmitted",
    "approved",
    "rejected",
    "withdrawn",
)

# Remark FSM statuses.
REMARK_STATUSES: tuple[str, ...] = (
    "open",
    "responded",
    "accepted",
    "contested",
    "withdrawn",
)

# Remark contestability classes. ``no_norm_ref_contestable`` is never chosen by
# the machine as a *decision*; it is the honest flag that a norm reference is
# missing and a human must confirm contestability.
REMARK_CLASSIFICATIONS: tuple[str, ...] = (
    "has_norm_ref",
    "no_norm_ref_contestable",
    "clarification",
    "defect",
)

REMARK_SEVERITIES: tuple[str, ...] = ("blocking", "major", "minor", "info")

# Decisions a caller may apply to a remark via /decide.
REMARK_DECISIONS: tuple[str, ...] = ("accepted", "contested", "withdrawn")

_AUTHORITY_KIND_PATTERN = "^(" + "|".join(AUTHORITY_KINDS) + ")$"
_SEVERITY_PATTERN = "^(" + "|".join(REMARK_SEVERITIES) + ")$"
_DECISION_PATTERN = "^(" + "|".join(REMARK_DECISIONS) + ")$"
_CLASSIFICATION_PATTERN = "^(" + "|".join(REMARK_CLASSIFICATIONS) + ")$"


# ── Cycle: create / update ─────────────────────────────────────────────


class ReviewCycleCreate(BaseModel):
    """Body for ``POST /v1/review_authority/cycles``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    authority_name: str = Field(..., min_length=1, max_length=255)
    authority_kind: str = Field(default="other", pattern=_AUTHORITY_KIND_PATTERN)
    submission_ref: str | None = Field(default=None, max_length=120)
    current_document_version: str = Field(default="", max_length=64)
    sla_days: int = Field(default=42, ge=1, le=3650)
    due_at: datetime | None = None
    jurisdiction: str | None = Field(default=None, max_length=64)
    notes: str = Field(default="", max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewCycleUpdate(BaseModel):
    """Body for ``PATCH /v1/review_authority/cycles/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    authority_name: str | None = Field(default=None, min_length=1, max_length=255)
    authority_kind: str | None = Field(default=None, pattern=_AUTHORITY_KIND_PATTERN)
    submission_ref: str | None = Field(default=None, max_length=120)
    # Moving the live document on: the pinned version does not change, so this
    # is what surfaces stale remarks.
    current_document_version: str | None = Field(default=None, max_length=64)
    sla_days: int | None = Field(default=None, ge=1, le=3650)
    due_at: datetime | None = None
    jurisdiction: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=10000)
    metadata: dict[str, Any] | None = None


class ReviewCycleSubmit(BaseModel):
    """Body for ``POST /v1/review_authority/cycles/{id}/submit``.

    The optional ``document_version`` overrides the version to pin at
    submission; when omitted the cycle's current document version is frozen.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    document_version: str | None = Field(default=None, max_length=64)
    submission_ref: str | None = Field(default=None, max_length=120)


class ReviewCycleTransition(BaseModel):
    """Body for ``POST /v1/review_authority/cycles/{id}/transition``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_status: str = Field(..., min_length=1, max_length=32)


class ReviewCycleResponse(BaseModel):
    """Review cycle returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    authority_name: str
    authority_kind: str = "other"
    submission_ref: str | None = None
    pinned_document_version: str | None = None
    current_document_version: str = ""
    status: str = "draft"
    opened_at: datetime | None = None
    due_at: datetime | None = None
    sla_days: int = 42
    jurisdiction: str | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Computed convenience fields.
    days_remaining: int | None = Field(
        default=None,
        description="Days to the SLA due date: negative when overdue, None until submitted.",
    )
    overdue: bool = Field(default=False, description="True when past the SLA due date and not yet decided.")


# ── Remark: create / respond / decide ──────────────────────────────────


class RemarkCreate(BaseModel):
    """Body for ``POST /v1/review_authority/cycles/{id}/remarks``.

    ``classification`` is normally left unset and derived from whether a
    ``norm_reference`` is present; a caller may still pass an explicit
    classification (``clarification`` / ``defect``) to override the default.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(..., min_length=1, max_length=10000)
    section: str | None = Field(default=None, max_length=120)
    norm_reference: str | None = Field(default=None, max_length=255)
    classification: str | None = Field(default=None, pattern=_CLASSIFICATION_PATTERN)
    severity: str = Field(default="major", pattern=_SEVERITY_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemarkRespond(BaseModel):
    """Body for ``POST /v1/review_authority/remarks/{id}/respond``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    response_text: str = Field(..., min_length=1, max_length=10000)


class RemarkDecide(BaseModel):
    """Body for ``POST /v1/review_authority/remarks/{id}/decide``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: str = Field(..., pattern=_DECISION_PATTERN)
    note: str | None = Field(default=None, max_length=10000)


class RemarkResponse(BaseModel):
    """Remark returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    cycle_id: UUID
    project_id: UUID
    ordinal: int
    section: str | None = None
    text: str
    norm_reference: str | None = None
    classification: str = "no_norm_ref_contestable"
    severity: str = "major"
    status: str = "open"
    response_text: str | None = None
    responded_at: datetime | None = None
    repeat_of_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Computed: True when the remark's cycle has moved past the pinned version.
    is_stale: bool = Field(
        default=False, description="True when the cycle's live document has moved past the pinned version."
    )


__all__ = [
    "AUTHORITY_KINDS",
    "CYCLE_STATUSES",
    "REMARK_CLASSIFICATIONS",
    "REMARK_DECISIONS",
    "REMARK_SEVERITIES",
    "REMARK_STATUSES",
    "RemarkCreate",
    "RemarkDecide",
    "RemarkRespond",
    "RemarkResponse",
    "ReviewCycleCreate",
    "ReviewCycleResponse",
    "ReviewCycleSubmit",
    "ReviewCycleTransition",
    "ReviewCycleUpdate",
]
