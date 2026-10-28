# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commissioning (Cx) Pydantic schemas - request/response models.

Create, update and response schemas for systems, checklists, checklist items
and issues, plus the readiness summary and the commission-action request.
Enum-like string fields are validated with regex patterns so an invalid value
is rejected at the edge with a 422 rather than reaching the database.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Shared regex patterns for the closed vocabularies.
_SYSTEM_TYPE_PATTERN = r"^(hvac|electrical|fire|plumbing|mechanical|controls|elevator|security|other)$"
_SYSTEM_STATUS_PATTERN = r"^(not_started|in_progress|tests_complete|commissioned)$"
_KIND_PATTERN = r"^(prefunctional|functional)$"
_ITEM_STATUS_PATTERN = r"^(pending|pass|fail|na)$"
_SEVERITY_PATTERN = r"^(low|medium|high|critical)$"
_ISSUE_STATUS_PATTERN = r"^(open|closed)$"


# ── Readiness summary ─────────────────────────────────────────────────────


class ReadinessSummary(BaseModel):
    """Explainable commissioning-readiness figure for a single system.

    Mirrors the pure dict from
    :func:`app.modules.commissioning.validators.compute_readiness`.
    """

    functional_total: int = 0
    functional_passed: int = 0
    functional_failed: int = 0
    functional_pending: int = 0
    functional_na: int = 0
    applicable: int = 0
    open_functional_items: int = 0
    open_critical_issues: int = 0
    readiness_pct: float = 0.0
    defined: bool = False
    can_commission: bool = False
    readiness_level: str = "red"
    blocking_reasons: list[str] = Field(default_factory=list)
    formula: str = ""


# ── System ─────────────────────────────────────────────────────────────────


class SystemCreate(BaseModel):
    """Create a new commissionable system."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    system_type: str = Field(default="hvac", pattern=_SYSTEM_TYPE_PATTERN)
    tag: str | None = Field(default=None, max_length=100)
    # Soft link to a plant register item; checked against the project when set.
    plant_item_id: str | None = Field(default=None, max_length=36)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str = Field(default="not_started", pattern=_SYSTEM_STATUS_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemUpdate(BaseModel):
    """Partial update for a commissionable system.

    ``status`` may be moved through the early lifecycle here, but a system can
    only reach ``commissioned`` through the gated ``/commission`` action, never
    a plain PATCH.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    system_type: str | None = Field(default=None, pattern=_SYSTEM_TYPE_PATTERN)
    tag: str | None = Field(default=None, max_length=100)
    # Soft link to a plant register item; checked against the project when set.
    plant_item_id: str | None = Field(default=None, max_length=36)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, pattern=_SYSTEM_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None


class SystemResponse(BaseModel):
    """A commissionable system returned from the API.

    ``readiness`` is populated on single-system reads and on the list endpoint
    so the dashboard can render a traffic-light per system without a follow-up
    request.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    system_type: str = "hvac"
    tag: str | None = None
    plant_item_id: str | None = None
    location: str | None = None
    description: str | None = None
    status: str = "not_started"
    commissioned_at: str | None = None
    commissioned_by: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    readiness: ReadinessSummary | None = None
    created_at: datetime
    updated_at: datetime


# ── Checklist ──────────────────────────────────────────────────────────────


class ChecklistCreate(BaseModel):
    """Create a new checklist within a system."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str = Field(default="prefunctional", pattern=_KIND_PATTERN)
    title: str = Field(..., min_length=1, max_length=255)
    # The commissioning stage this checklist documents, when a quality concept defines stages.
    stage_code: str | None = Field(default=None, max_length=40)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChecklistUpdate(BaseModel):
    """Partial update for a checklist."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str | None = Field(default=None, pattern=_KIND_PATTERN)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] | None = None


class ChecklistResponse(BaseModel):
    """A checklist returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    system_id: UUID
    kind: str = "prefunctional"
    title: str
    stage_code: str | None = None
    description: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Checklist item ─────────────────────────────────────────────────────────


class ItemCreate(BaseModel):
    """Create a new checklist item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1)
    sequence: int = Field(default=0, ge=0)
    status: str = Field(default="pending", pattern=_ITEM_STATUS_PATTERN)
    result_note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ItemUpdate(BaseModel):
    """Partial update for a checklist item (description / order / status)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, min_length=1)
    sequence: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern=_ITEM_STATUS_PATTERN)
    result_note: str | None = None
    metadata: dict[str, Any] | None = None


class ItemResultRequest(BaseModel):
    """Record a pass / fail / na result against a checklist item.

    ``status`` is restricted to a real result (never ``pending``) so this
    endpoint always represents a deliberate verification; clear a result back to
    pending via ``PATCH`` instead.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    status: str = Field(..., pattern=r"^(pass|fail|na)$")
    result_note: str | None = Field(default=None, max_length=2000)


class ItemResponse(BaseModel):
    """A checklist item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    checklist_id: UUID
    sequence: int = 0
    description: str
    status: str = "pending"
    result_note: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Issue ──────────────────────────────────────────────────────────────────


class IssueCreate(BaseModel):
    """Create a new issue against a system."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1)
    severity: str = Field(default="medium", pattern=_SEVERITY_PATTERN)
    status: str = Field(default="open", pattern=_ISSUE_STATUS_PATTERN)
    resolution: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IssueUpdate(BaseModel):
    """Partial update for an issue (severity, close it with a resolution ...)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, min_length=1)
    severity: str | None = Field(default=None, pattern=_SEVERITY_PATTERN)
    status: str | None = Field(default=None, pattern=_ISSUE_STATUS_PATTERN)
    resolution: str | None = None
    metadata: dict[str, Any] | None = None


class IssueResponse(BaseModel):
    """An issue returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    system_id: UUID
    description: str
    severity: str = "medium"
    status: str = "open"
    resolution: str | None = None
    raised_by: str | None = None
    closed_by: str | None = None
    closed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Commission action + stats ──────────────────────────────────────────────


class CommissionRequest(BaseModel):
    """Request body for the gated commission action."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note: str | None = Field(default=None, max_length=2000)


class CxStatsResponse(BaseModel):
    """Aggregate commissioning statistics for a project."""

    total_systems: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    commissioned: int = 0
    open_issues: int = 0
    open_critical_issues: int = 0
    average_readiness_pct: float = 0.0
