"""Schedule Pydantic schemas — request/response models.

Defines create, update, and response schemas for schedules, activities,
and work orders.  Numeric values (costs, progress) are exposed as floats
in the API but stored as strings in SQLite-compatible models.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Schedule schemas ─────────────────────────────────────────────────────────


class ScheduleCreate(BaseModel):
    """Create a new schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    start_date: str | None = Field(default=None, max_length=20)
    end_date: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduleUpdate(BaseModel):
    """Partial update for a schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_date: str | None = Field(default=None, max_length=20)
    end_date: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, pattern=r"^(draft|active|completed)$")
    metadata: dict[str, Any] | None = None


class ScheduleResponse(BaseModel):
    """Schedule returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str
    start_date: str | None
    end_date: str | None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Activity schemas ─────────────────────────────────────────────────────────


class ActivityDependency(BaseModel):
    """Dependency between two activities."""

    activity_id: UUID
    type: str = Field(default="FS", pattern=r"^(FS|SS|FF|SF)$")
    lag_days: int = 0


class ActivityResource(BaseModel):
    """Resource allocation for an activity."""

    name: str
    type: str = ""
    allocation_pct: float = 100.0


class ActivityCreate(BaseModel):
    """Create a new activity."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schedule_id: UUID = Field(default=None)  # type: ignore[assignment]
    parent_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    wbs_code: str = Field(default="", max_length=50)
    start_date: str = Field(..., max_length=20)
    end_date: str = Field(..., max_length=20)
    duration_days: int = Field(default=0, ge=0)
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    status: str = Field(
        default="not_started",
        pattern=r"^(not_started|in_progress|completed|delayed)$",
    )
    activity_type: str = Field(default="task", pattern=r"^(task|milestone|summary)$")
    dependencies: list[ActivityDependency] = Field(default_factory=list)
    resources: list[ActivityResource] = Field(default_factory=list)
    boq_position_ids: list[UUID] = Field(default_factory=list)
    color: str = Field(default="#0071e3", max_length=20)
    sort_order: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivityUpdate(BaseModel):
    """Partial update for an activity."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    wbs_code: str | None = Field(default=None, max_length=50)
    start_date: str | None = Field(default=None, max_length=20)
    end_date: str | None = Field(default=None, max_length=20)
    duration_days: int | None = Field(default=None, ge=0)
    progress_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    status: str | None = Field(
        default=None,
        pattern=r"^(not_started|in_progress|completed|delayed)$",
    )
    activity_type: str | None = Field(default=None, pattern=r"^(task|milestone|summary)$")
    dependencies: list[ActivityDependency] | None = None
    resources: list[ActivityResource] | None = None
    boq_position_ids: list[UUID] | None = None
    color: str | None = Field(default=None, max_length=20)
    sort_order: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None


class ActivityResponse(BaseModel):
    """Activity returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    schedule_id: UUID
    parent_id: UUID | None
    name: str
    description: str
    wbs_code: str
    start_date: str
    end_date: str
    duration_days: int
    progress_pct: float
    status: str
    activity_type: str
    dependencies: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    boq_position_ids: list[str]
    color: str
    sort_order: int
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class LinkPositionRequest(BaseModel):
    """Request body for linking a BOQ position to an activity."""

    boq_position_id: UUID


class ProgressUpdateRequest(BaseModel):
    """Request body for updating activity progress."""

    progress_pct: float = Field(..., ge=0.0, le=100.0)


# ── Work Order schemas ───────────────────────────────────────────────────────


class WorkOrderCreate(BaseModel):
    """Create a new work order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    activity_id: UUID = Field(default=None)  # type: ignore[assignment]
    assembly_id: UUID | None = None
    boq_position_id: UUID | None = None
    code: str = Field(..., min_length=1, max_length=50)
    description: str = ""
    assigned_to: str = Field(default="", max_length=255)
    planned_start: str | None = Field(default=None, max_length=20)
    planned_end: str | None = Field(default=None, max_length=20)
    actual_start: str | None = Field(default=None, max_length=20)
    actual_end: str | None = Field(default=None, max_length=20)
    planned_cost: float = Field(default=0.0, ge=0.0)
    actual_cost: float = Field(default=0.0, ge=0.0)
    status: str = Field(
        default="planned",
        pattern=r"^(planned|issued|in_progress|completed|cancelled)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkOrderUpdate(BaseModel):
    """Partial update for a work order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    assembly_id: UUID | None = None
    boq_position_id: UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = None
    assigned_to: str | None = Field(default=None, max_length=255)
    planned_start: str | None = Field(default=None, max_length=20)
    planned_end: str | None = Field(default=None, max_length=20)
    actual_start: str | None = Field(default=None, max_length=20)
    actual_end: str | None = Field(default=None, max_length=20)
    planned_cost: float | None = Field(default=None, ge=0.0)
    actual_cost: float | None = Field(default=None, ge=0.0)
    status: str | None = Field(
        default=None,
        pattern=r"^(planned|issued|in_progress|completed|cancelled)$",
    )
    metadata: dict[str, Any] | None = None


class WorkOrderStatusUpdate(BaseModel):
    """Request body for updating work order status."""

    status: str = Field(..., pattern=r"^(planned|issued|in_progress|completed|cancelled)$")


class WorkOrderResponse(BaseModel):
    """Work order returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    activity_id: UUID
    assembly_id: UUID | None
    boq_position_id: UUID | None
    code: str
    description: str
    assigned_to: str
    planned_start: str | None
    planned_end: str | None
    actual_start: str | None
    actual_end: str | None
    planned_cost: float
    actual_cost: float
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Composite schemas ────────────────────────────────────────────────────────


class ScheduleWithActivities(ScheduleResponse):
    """Schedule with all its activities."""

    activities: list[ActivityResponse] = Field(default_factory=list)


class GanttActivity(BaseModel):
    """Single activity formatted for Gantt chart rendering."""

    id: UUID
    name: str
    start: str
    end: str
    progress: float
    dependencies: list[dict[str, Any]]
    parent_id: UUID | None
    color: str
    boq_positions: list[str]
    wbs_code: str
    activity_type: str
    status: str


class GanttSummary(BaseModel):
    """Summary statistics for a Gantt chart."""

    total_activities: int = 0
    completed: int = 0
    in_progress: int = 0
    delayed: int = 0
    not_started: int = 0


class GanttData(BaseModel):
    """Structured data for Gantt chart rendering."""

    activities: list[GanttActivity] = Field(default_factory=list)
    summary: GanttSummary = Field(default_factory=GanttSummary)
