# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Off-site / Prefab / DfMA Pydantic schemas (request/response models)."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.prefab.guard import STAGE_ORDER, UNIT_TYPES

# Build the API-validation regexes from the canonical vocabularies in guard.py
# so the request validation and the state machine can never drift apart.
_STATUS_PATTERN = "^(" + "|".join(STAGE_ORDER) + ")$"
_TYPE_PATTERN = "^(" + "|".join(UNIT_TYPES) + ")$"


# ── Unit Create ───────────────────────────────────────────────────────────


class PrefabUnitCreate(BaseModel):
    """Create a new off-site unit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    ref: str = Field(..., min_length=1, max_length=120)
    unit_type: str = Field(default="module", pattern=_TYPE_PATTERN)
    status: str = Field(default="design", pattern=_STATUS_PATTERN)
    target_install_date: date | None = None
    drawing_ref: str | None = Field(default=None, max_length=255)
    bim_element_ids: list[str] | None = None
    notes: str | None = None


# ── Unit Update ───────────────────────────────────────────────────────────


class PrefabUnitUpdate(BaseModel):
    """Partial update for an off-site unit.

    ``status`` is deliberately NOT updatable here - a stage change must go
    through ``POST /units/{id}/advance`` so it passes the ordered state machine
    and the QA gate, and leaves a ``ProductionEvent`` audit row. Allowing a bare
    PATCH of ``status`` would let a caller skip QA entirely.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    ref: str | None = Field(default=None, min_length=1, max_length=120)
    unit_type: str | None = Field(default=None, pattern=_TYPE_PATTERN)
    target_install_date: date | None = None
    drawing_ref: str | None = Field(default=None, max_length=255)
    bim_element_ids: list[str] | None = None
    notes: str | None = None


# ── Unit Response ─────────────────────────────────────────────────────────


class PrefabUnitResponse(BaseModel):
    """Off-site unit returned from the API.

    Beyond the stored fields, the read model surfaces a derived cost view when
    the unit is linked to a BOQ position and/or an assembly (Spine 4). Money is
    always a Decimal serialised as a string so large currency values round-trip
    exactly and stay locale-neutral.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    ref: str
    unit_type: str
    status: str
    target_install_date: date | None = None
    drawing_ref: str | None = None
    bim_element_ids: list[str] | None = None
    notes: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # ── Spine 4: optional cost links + derived cost view ─────────────────
    boq_position_id: UUID | None = None
    assembly_id: UUID | None = None
    # The linked cost basis: the BOQ position's ``unit_rate`` (preferred) or the
    # assembly's ``total_rate``. ``None`` when the unit is not linked.
    cost_basis: str | None = None
    # Which link drove ``cost_basis``: "boq_position" | "assembly" | None.
    cost_source: str | None = None
    # Production progress in 0..1 from the stage machine (design=0, installed=1).
    completed_fraction: float | None = None
    # Simple earned value: ``cost_basis * completed_fraction`` (Decimal string).
    earned_value: str | None = None


# ── Unit Cost Link ────────────────────────────────────────────────────────


class PrefabUnitLinkRequest(BaseModel):
    """Set or clear a unit's cost links to a BOQ position and/or an assembly.

    Send a UUID to set a link, or an explicit ``null`` to clear it. Omit a field
    entirely to leave that link untouched, so one link can change without
    disturbing the other. An empty body is a harmless no-op.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID | None = None
    assembly_id: UUID | None = None


# ── Advance Stage ─────────────────────────────────────────────────────────


class AdvanceStageRequest(BaseModel):
    """Advance a unit to its next production stage, or to an explicit target.

    When ``target_status`` is omitted the unit advances to the very next stage
    in the lifecycle. Providing a target lets a caller jump ahead - still
    subject to the forward-only and QA-gate rules enforced by the state machine.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    target_status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    note: str | None = Field(default=None, max_length=2000)


# ── Production Event (audit trail) ────────────────────────────────────────


class ProductionEventResponse(BaseModel):
    """A single row in a unit's production-stage audit log."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    unit_id: UUID
    stage: str
    from_stage: str | None = None
    at: datetime
    note: str | None = None
    created_by: str | None = None


# ── Stage vocabulary (lookup) ─────────────────────────────────────────────


class PrefabStageInfo(BaseModel):
    """One stage in the ordered lifecycle (drives the board columns)."""

    stage: str
    index: int
    is_post_qa: bool


class PrefabStagesResponse(BaseModel):
    """The ordered production stages plus the recognised unit types."""

    stages: list[PrefabStageInfo] = Field(default_factory=list)
    unit_types: list[str] = Field(default_factory=list)


# ── Board (status kanban) ─────────────────────────────────────────────────


class PrefabBoardColumn(BaseModel):
    """One kanban column: a production stage with its units."""

    stage: str
    count: int = 0
    units: list[PrefabUnitResponse] = Field(default_factory=list)


class PrefabBoardResponse(BaseModel):
    """Board grouped by production stage, in lifecycle order."""

    project_id: UUID
    total: int = 0
    columns: list[PrefabBoardColumn] = Field(default_factory=list)


# ── Stats ─────────────────────────────────────────────────────────────────


class PrefabStatsResponse(BaseModel):
    """Aggregate statistics for a project's off-site units."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
