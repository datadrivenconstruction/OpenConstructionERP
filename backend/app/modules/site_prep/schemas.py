# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site-prep Pydantic v2 schemas (request / response models).

Calendar dates cross the wire as ISO-8601 strings (``YYYY-MM-DD``) and are typed
as :class:`datetime.date` on create/update so Pydantic parses and validates them.
The readiness rollup response reports percentages as ``float | None`` (``None``
meaning "undefined", e.g. a category with no applicable items) and dates as ISO
strings, mirroring the dict produced by the pure
:mod:`app.modules.site_prep.readiness` core.

The category / status vocabularies are the single source of truth in
:mod:`app.modules.site_prep.readiness`; the ``Literal`` types below enumerate the
same values so an out-of-vocabulary value is rejected at the edge (422).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Vocabularies (kept in lock-step with app.modules.site_prep.readiness).
CategoryLiteral = Literal[
    "access",
    "accommodation_welfare",
    "temporary_utilities",
    "security_hoarding",
    "temporary_works",
    "environmental_controls",
    "logistics_laydown",
    "permits_consents",
    "inductions_training",
    "other",
]
ItemStatusLiteral = Literal[
    "not_started",
    "in_progress",
    "ready",
    "blocked",
    "not_applicable",
]
PlanStatusLiteral = Literal["draft", "active", "complete"]


# -- Mobilisation plan -------------------------------------------------------


class SitePrepPlanCreate(BaseModel):
    """Create the mobilisation plan for a project (one per project)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_start_date: date | None = None
    status: PlanStatusLiteral = "draft"
    notes: str | None = Field(default=None, max_length=20000)


class SitePrepPlanUpdate(BaseModel):
    """Patch the mobilisation plan. Only fields provided are changed.

    A field explicitly set to ``null`` clears it; an omitted field is left
    untouched (the service applies ``exclude_unset``).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    target_start_date: date | None = None
    status: PlanStatusLiteral | None = None
    notes: str | None = Field(default=None, max_length=20000)


class SitePrepPlanResponse(BaseModel):
    """A mobilisation plan returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    target_start_date: date | None = None
    status: str
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# -- Readiness item ----------------------------------------------------------


class SitePrepItemCreate(BaseModel):
    """Create a single readiness item on a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plan_id: UUID | None = None
    category: CategoryLiteral
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    status: ItemStatusLiteral = "not_started"
    responsible_party: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    completed_date: date | None = None
    is_gate: bool = False
    sort_order: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=20000)


class SitePrepItemUpdate(BaseModel):
    """Patch a readiness item. Only fields provided are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plan_id: UUID | None = None
    category: CategoryLiteral | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    status: ItemStatusLiteral | None = None
    responsible_party: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    completed_date: date | None = None
    is_gate: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=20000)


class SitePrepItemResponse(BaseModel):
    """A readiness item returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    plan_id: UUID | None = None
    category: str
    title: str
    description: str | None = None
    status: str
    responsible_party: str | None = None
    due_date: date | None = None
    completed_date: date | None = None
    is_gate: bool
    sort_order: int
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# -- Derived readiness views -------------------------------------------------


class ReadinessItemRef(BaseModel):
    """A lightweight reference to an item, used in blocked / overdue lists."""

    item_id: str | None = None
    title: str
    category: str
    status: str
    is_gate: bool
    due_date: str | None = None


class CategoryReadinessResponse(BaseModel):
    """Readiness rollup for one category (or the overall project)."""

    category: str
    total: int
    applicable: int
    ready: int
    counts: dict[str, int]
    readiness_percent: float | None = None
    gate_total: int
    gate_ready: bool
    blocked: int
    overdue: int


class ReadinessReportResponse(BaseModel):
    """The full mobilisation readiness rollup for a project."""

    project_id: UUID
    as_of: str
    target_start_date: str | None = None
    days_to_target: int | None = None
    gate_ready: bool
    on_track: bool
    total_items: int
    applicable_items: int
    ready_items: int
    readiness_percent: float | None = None
    overall: CategoryReadinessResponse
    categories: list[CategoryReadinessResponse] = Field(default_factory=list)
    blocked_items: list[ReadinessItemRef] = Field(default_factory=list)
    overdue_items: list[ReadinessItemRef] = Field(default_factory=list)


class GateStatusResponse(BaseModel):
    """Commencement-gate status for a project.

    Answers the single question a site manager asks before mobilising: are all
    the hard prerequisites to start on site satisfied, and if not, which items
    are still blocking?
    """

    project_id: UUID
    as_of: str
    target_start_date: str | None = None
    days_to_target: int | None = None
    gate_ready: bool
    on_track: bool
    gate_total: int
    gate_ready_count: int
    gate_blocking: list[ReadinessItemRef] = Field(default_factory=list)
