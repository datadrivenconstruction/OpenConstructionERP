"""Requirements & Quality Gates Pydantic schemas — request/response models.

Defines create, update, and response schemas for requirement sets,
individual requirements (EAC triplets), and quality gate results.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Requirement schemas ─────────────────────────────────────────────────────


class RequirementCreate(BaseModel):
    """Create a new EAC requirement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity: str = Field(..., min_length=1, max_length=255)
    attribute: str = Field(..., min_length=1, max_length=255)
    constraint_type: str = Field(
        default="equals",
        pattern=r"^(equals|min|max|range|contains|regex)$",
    )
    constraint_value: str = Field(..., min_length=1, max_length=500)
    unit: str = Field(default="", max_length=50)
    category: str = Field(default="general", max_length=100)
    priority: str = Field(
        default="must",
        pattern=r"^(must|should|may)$",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_ref: str = Field(default="", max_length=500)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementUpdate(BaseModel):
    """Partial update for a requirement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity: str | None = Field(default=None, min_length=1, max_length=255)
    attribute: str | None = Field(default=None, min_length=1, max_length=255)
    constraint_type: str | None = Field(
        default=None,
        pattern=r"^(equals|min|max|range|contains|regex)$",
    )
    constraint_value: str | None = Field(default=None, min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    priority: str | None = Field(
        default=None,
        pattern=r"^(must|should|may)$",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_ref: str | None = Field(default=None, max_length=500)
    status: str | None = Field(
        default=None,
        pattern=r"^(open|verified|linked|conflict)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class RequirementResponse(BaseModel):
    """Requirement item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    requirement_set_id: UUID
    entity: str
    attribute: str
    constraint_type: str
    constraint_value: str
    unit: str = ""
    category: str = "general"
    priority: str = "must"
    confidence: float | None = None
    source_ref: str = ""
    status: str = "open"
    linked_position_id: UUID | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── RequirementSet schemas ──────────────────────────────────────────────────


class RequirementSetCreate(BaseModel):
    """Create a new requirement set."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    source_type: str = Field(
        default="manual",
        pattern=r"^(manual|pdf|cad|bim|specification)$",
    )
    source_filename: str = Field(default="", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementSetUpdate(BaseModel):
    """Partial update for a requirement set.

    All fields are optional — pass only what should change.  Project
    re-assignment is intentionally NOT supported here (sets are
    project-scoped at creation; moving them would silently break
    every BIM/BOQ link they own).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    source_type: str | None = Field(
        default=None,
        pattern=r"^(manual|pdf|cad|bim|specification)$",
    )
    source_filename: str | None = Field(default=None, max_length=500)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|active|locked|archived)$",
    )
    metadata: dict[str, Any] | None = None


class RequirementBulkDeleteRequest(BaseModel):
    """Body of the bulk-delete endpoint.

    A single transaction deletes every requirement whose id is in the
    list.  Ids that do not belong to the path's ``set_id`` are silently
    skipped — the endpoint reports the actual delete count so callers
    can detect that case.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    requirement_ids: list[UUID] = Field(..., min_length=1, max_length=500)


class RequirementBulkDeleteResult(BaseModel):
    """Response from the bulk-delete endpoint."""

    deleted_count: int = 0
    skipped_count: int = 0


class RequirementSetResponse(BaseModel):
    """Requirement set returned from the API (without nested requirements)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    source_type: str = "manual"
    source_filename: str = ""
    status: str = "draft"
    gate_status: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class RequirementSetDetail(BaseModel):
    """Requirement set with nested requirements and gate results."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    source_type: str = "manual"
    source_filename: str = ""
    status: str = "draft"
    gate_status: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    requirements: list[RequirementResponse] = Field(default_factory=list)
    gate_results: list["GateResultResponse"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── GateResult schemas ──────────────────────────────────────────────────────


class GateResultResponse(BaseModel):
    """Quality gate result returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    requirement_set_id: UUID
    gate_number: int
    gate_name: str
    status: str = "skipped"
    score: float = 0.0
    findings: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


# ── Stats schemas ───────────────────────────────────────────────────────────


class RequirementStats(BaseModel):
    """Aggregated requirement stats for a project."""

    total_requirements: int = 0
    total_sets: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    linked_count: int = 0
    unlinked_count: int = 0


# ── Text import schema ─────────────────────────────────────────────────────


class TextImportRequest(BaseModel):
    """Request body for importing requirements from structured text."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(..., min_length=1)
    set_name: str = Field(default="Imported Requirements", max_length=255)
    default_category: str = Field(default="general", max_length=100)
    default_priority: str = Field(
        default="must",
        pattern=r"^(must|should|may)$",
    )
