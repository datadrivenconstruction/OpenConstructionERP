# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Pydantic schemas - request/response models.

Defines create, update, and response schemas for schedules, activities,
and work orders.  Numeric values are stored as strings in SQLite-compatible
models. v3 §10 money fields (work order ``planned_cost`` / ``actual_cost``,
labour-by-phase ``labor_cost`` / ``total_cost``) are emitted as
Decimal-as-string in JSON.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.core.cpm import canonical_exception_dates, check_work_days_in_range


def _check_calendar_metadata(metadata: Any) -> None:
    """Refuse a schedule calendar override the CPM engine cannot count.

    A schedule's ``metadata`` is free-form and is stored as given, so
    ``{"calendar": {"work_days": [...]}}`` reaches
    :func:`app.modules.schedule.service.resolve_calendar` and from there the CPM
    engine without passing the ``schedule_advanced`` calendar schemas. It is a
    second way into the same Monday-zero convention and needs the same refusal.

    Both halves of the override are inspected, and for the same reason. A
    weekday the engine cannot count produces a shorter week; an exception date
    the engine cannot read is dropped, so a day the user marked as a holiday is
    worked. Neither is reported anywhere the writer can see it, which is what
    makes the write the last place either can still be refused.

    ``exceptions`` is normalised in place before it is stored, so an unambiguous
    but untidy entry is accepted rather than refused: a date pasted from a
    spreadsheet arrives as ``"2026-05-01 "``, and an export may write
    ``"2026-05-01T00:00:00"``. Storing the canonical form also settles it for
    the reader in ``progress_math``, which compares ISO strings without parsing
    them and so would otherwise miss both spellings in silence.

    Everything else is left to the resolver, which coerces defensively and has
    to keep doing so for schedules written before these checks existed.

    Args:
        metadata: The schedule's metadata mapping, or anything else.

    Raises:
        ValueError: If the override declares a weekday outside Monday=0..Sunday=6,
            or an exception entry that names no single day.
    """
    if not isinstance(metadata, dict):
        return
    calendar = metadata.get("calendar")
    if not isinstance(calendar, dict):
        return
    _check_calendar_override(calendar, source="metadata.calendar")


def _check_calendar_override(calendar: dict[str, Any], *, source: str) -> None:
    """Refuse, and where it can, repair one work-calendar override.

    The checks live here rather than in a single caller because the engine has
    more than one entrance. A calendar reaches it through a schedule's
    ``metadata`` and through the CPM endpoint's request body, and neither passes
    the ``schedule_advanced`` calendar schemas on the way. Both entrances need
    the same refusal, so a third one added later joins by calling this with its
    own ``source`` rather than by growing a second copy of the rules.

    Args:
        calendar: The override mapping. ``exceptions`` is normalised in place.
        source: Dotted path of the override within the request body. It is
            prefixed onto the field name in every error, so the message names
            the field the writer has to correct rather than a field that merely
            resembles it.

    Raises:
        ValueError: If the override declares a weekday outside Monday=0..Sunday=6,
            or an exception entry that names no single day.
    """
    check_work_days_in_range(calendar.get("work_days"), source=f"{source}.work_days")
    if "exceptions" in calendar:
        canonical = canonical_exception_dates(calendar["exceptions"], source=f"{source}.exceptions")
        if canonical is not None:
            calendar["exceptions"] = canonical


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py - money fields are stored /
# accepted as Decimal but emitted as plain decimal strings in JSON.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# Bound ints at PostgreSQL INT4 max.
_INT32_MAX = 2_147_483_647
# Schedules don't go beyond ~100 years (36500 days). A 10x safety margin.
_MAX_SCHEDULE_DAYS = 365_000


def _parse_iso_date(value: str | None, field_name: str) -> date | None:
    """Parse a YYYY-MM-DD prefix into a real calendar ``date``.

    The Pydantic regex ``^\\d{4}-\\d{2}-\\d{2}$`` is structural - it accepts
    impossible dates like ``2026-02-30`` or ``2026-13-99``. We re-parse via
    :func:`datetime.date.fromisoformat` to reject those before they propagate
    into compute_duration() and yield bogus durations.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"{field_name} ({value[:10]}) is not a valid calendar date") from exc


def _validate_date_range(start: str | None, end: str | None) -> None:
    """Reject schedules/activities where end_date is before start_date,
    and reject impossible calendar dates (Feb 30, month 13, etc.).
    """
    parsed_start = _parse_iso_date(start, "start_date")
    parsed_end = _parse_iso_date(end, "end_date")
    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise ValueError(
            f"end_date ({parsed_end.isoformat()}) must be on or after start_date ({parsed_start.isoformat()})"
        )


# ── Schedule schemas ─────────────────────────────────────────────────────────


class ScheduleCreate(BaseModel):
    """Create a new schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255, examples=["Master Schedule Phase 1"])
    schedule_type: str = Field(default="master", max_length=50, examples=["master"])
    description: str = Field(default="", max_length=5000)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20, examples=["2026-05-01"])
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20, examples=["2027-03-31"])
    data_date: str | None = Field(default=None, max_length=20)
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_dates(self) -> "ScheduleCreate":
        _validate_date_range(self.start_date, self.end_date)
        _check_calendar_metadata(self.metadata)
        return self


class ScheduleUpdate(BaseModel):
    """Partial update for a schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    schedule_type: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    status: str | None = Field(default=None, pattern=r"^(draft|active|completed|frozen|archived)$")
    data_date: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "ScheduleUpdate":
        _validate_date_range(self.start_date, self.end_date)
        _check_calendar_metadata(self.metadata)
        return self


class ScheduleResponse(BaseModel):
    """Schedule returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    schedule_type: str = "master"
    description: str
    start_date: str | None
    end_date: str | None
    status: str
    data_date: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    """One page of schedules plus the size of the whole set.

    ``total`` is the row count matching the filter, not the length of
    ``items``. A client that renders ``items`` without reading ``total``
    shows a truncated list and cannot tell that it did.
    """

    items: list[ScheduleResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Activity schemas ─────────────────────────────────────────────────────────


class ActivityDependency(BaseModel):
    """Dependency between two activities."""

    model_config = ConfigDict(extra="ignore")

    activity_id: UUID
    type: str = Field(default="FS", pattern=r"^(FS|SS|FF|SF)$")
    # Negative lag allowed (lead time); bound both sides at int32.
    lag_days: int = Field(default=0, ge=-_INT32_MAX, le=_INT32_MAX)


class ActivityResource(BaseModel):
    """Resource allocation for an activity."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., max_length=255)
    type: str = Field(default="", max_length=100)
    allocation_pct: float = Field(default=100.0, ge=0.0, le=1000.0, allow_inf_nan=False)


class ActivityCreate(BaseModel):
    """Create a new activity.

    v3 §10 - ``cost_planned`` / ``cost_actual`` are money;
    Decimal-as-string in JSON. ``budgeted_units`` / ``installed_units``
    are quantities and travel the same way.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    schedule_id: UUID = Field(default=None)  # type: ignore[assignment]
    parent_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    wbs_code: str = Field(default="", max_length=50)
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    # ``None`` triggers auto-computation from start/end dates. Explicit ``0``
    # is respected so milestone-style zero-duration activities are creatable.
    duration_days: int | None = Field(default=None, ge=0, le=_MAX_SCHEDULE_DAYS)
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0, allow_inf_nan=False)
    status: str = Field(
        default="not_started",
        pattern=r"^(not_started|in_progress|completed|delayed)$",
    )
    activity_type: str = Field(default="task", pattern=r"^(task|milestone|summary)$")
    dependencies: list[ActivityDependency] = Field(default_factory=list, max_length=1000)
    resources: list[ActivityResource] = Field(default_factory=list, max_length=1000)
    boq_position_ids: list[UUID] = Field(default_factory=list, max_length=10_000)
    color: str = Field(default="#0071e3", max_length=20)
    sort_order: int = Field(default=0, ge=0, le=_INT32_MAX)
    constraint_type: str | None = Field(default=None, max_length=50)
    constraint_date: str | None = Field(default=None, max_length=20)
    activity_code: str | None = Field(default=None, max_length=50)
    bim_element_ids: list[str] | None = Field(default=None, max_length=100_000)
    # ── Cost-loaded / progress-rigor columns ──────────────────────────────
    # ``None`` means "not cost-loaded", which is what the nullable ORM columns
    # already encode; the EVM rollup reads a missing amount as zero. Bounds
    # mirror the work-order money pair. The unit quantities take ``ge=0`` only,
    # matching ``progress_schemas.TypedProgressRequest``, which is the other
    # writer of the same two columns.
    cost_planned: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"))
    cost_actual: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"))
    percent_complete_type: str = Field(default="physical", pattern=r"^(physical|duration|units)$")
    remaining_duration: int | None = Field(default=None, ge=0, le=_MAX_SCHEDULE_DAYS)
    budgeted_units: Decimal | None = Field(default=None, ge=0)
    installed_units: Decimal | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cost_planned", "cost_actual", "budgeted_units", "installed_units", mode="after")
    @classmethod
    def _reject_non_finite(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("amount must be finite (no NaN / Infinity)")
        return v

    @field_serializer("cost_planned", "cost_actual", "budgeted_units", "installed_units", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)

    @model_validator(mode="after")
    def _check_dates(self) -> "ActivityCreate":
        _validate_date_range(self.start_date, self.end_date)
        return self


class ActivityUpdate(BaseModel):
    """Partial update for an activity.

    The cost and unit fields write the raw columns, the way ``progress_pct``
    already does here. The percent-complete engine lives behind
    ``PATCH /activities/{id}/typed-progress/``; that endpoint stays the place
    that derives a percent from units and recomputes the remaining duration.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    parent_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    wbs_code: str | None = Field(default=None, max_length=50)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    duration_days: int | None = Field(default=None, ge=0, le=_MAX_SCHEDULE_DAYS)
    progress_pct: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)
    status: str | None = Field(
        default=None,
        pattern=r"^(not_started|in_progress|completed|delayed)$",
    )
    activity_type: str | None = Field(default=None, pattern=r"^(task|milestone|summary)$")
    dependencies: list[ActivityDependency] | None = Field(default=None, max_length=1000)
    resources: list[ActivityResource] | None = Field(default=None, max_length=1000)
    boq_position_ids: list[UUID] | None = Field(default=None, max_length=10_000)
    color: str | None = Field(default=None, max_length=20)
    sort_order: int | None = Field(default=None, ge=0, le=_INT32_MAX)
    constraint_type: str | None = Field(default=None, max_length=50)
    constraint_date: str | None = Field(default=None, max_length=20)
    activity_code: str | None = Field(default=None, max_length=50)
    bim_element_ids: list[str] | None = Field(default=None, max_length=100_000)
    # ── Cost-loaded / progress-rigor columns ──────────────────────────────
    cost_planned: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"))
    cost_actual: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"))
    percent_complete_type: str | None = Field(default=None, pattern=r"^(physical|duration|units)$")
    remaining_duration: int | None = Field(default=None, ge=0, le=_MAX_SCHEDULE_DAYS)
    budgeted_units: Decimal | None = Field(default=None, ge=0)
    installed_units: Decimal | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None

    @field_validator("cost_planned", "cost_actual", "budgeted_units", "installed_units", mode="after")
    @classmethod
    def _reject_non_finite(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("amount must be finite (no NaN / Infinity)")
        return v

    @field_serializer("cost_planned", "cost_actual", "budgeted_units", "installed_units", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)

    @model_validator(mode="after")
    def _check_dates(self) -> "ActivityUpdate":
        _validate_date_range(self.start_date, self.end_date)
        return self


class ActivityResponse(BaseModel):
    """Activity returned from the API.

    v3 §10 - ``cost_planned`` / ``cost_actual`` are money;
    Decimal-as-string in JSON, as are the two unit quantities.
    """

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

    # CPM result fields (Phase 13)
    early_start: str | None = None
    early_finish: str | None = None
    late_start: str | None = None
    late_finish: str | None = None
    total_float: int | None = None
    free_float: int | None = None
    is_critical: bool = False

    # Constraint, code, BIM fields
    constraint_type: str | None = None
    constraint_date: str | None = None
    activity_code: str | None = None
    bim_element_ids: list[str] | None = None

    # Per-activity work calendar (schedule_advanced Calendar). Set via the
    # dedicated PUT /activities/{id}/calendar/ endpoint; exposed here so the
    # grid can show and pick the activity's calendar. None -> schedule default.
    calendar_id: UUID | None = None

    # ── Cost-loaded / progress-rigor columns ──────────────────────────────
    # ``cost_planned`` is the activity's share of BAC, so a client that cannot
    # read it back cannot tell a cost-loaded schedule from an empty one.
    cost_planned: Decimal | None = None
    cost_actual: Decimal | None = None
    percent_complete_type: str = "physical"
    remaining_duration: int | None = None
    budgeted_units: Decimal | None = None
    installed_units: Decimal | None = None

    @field_serializer("cost_planned", "cost_actual", "budgeted_units", "installed_units", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class ActivityListResponse(BaseModel):
    """One page of activities plus the size of the whole set.

    ``total`` is the activity count of the schedule, not the length of
    ``items``. The default page is large (1000), which is exactly why the
    truncation is easy to miss: a schedule only has to cross that line once
    for a viewer to start drawing an incomplete programme.
    """

    items: list[ActivityResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 1000


class LinkPositionRequest(BaseModel):
    """Request body for linking a BOQ position to an activity."""

    boq_position_id: UUID


class ActivityBimLinkRequest(BaseModel):
    """Request body for replacing the BIM element link set on an activity.

    The full ``bim_element_ids`` list is replaced atomically - callers that
    want to add/remove a single element should read the current list, mutate
    it, then PATCH the whole array back.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    bim_element_ids: list[str] = Field(default_factory=list)


class ActivityBrief(BaseModel):
    """Lightweight activity summary embedded in a BIM element response.

    Mirrors the ``ActivityBrief`` schema declared in ``bim_hub.schemas`` -
    the two are kept in sync so the viewer can render schedule badges on
    linked elements without a second round trip.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    start_date: str | None = None
    end_date: str | None = None
    status: str
    percent_complete: float = 0.0


class ProgressUpdateRequest(BaseModel):
    """Request body for updating activity progress."""

    progress_pct: float = Field(..., ge=0.0, le=100.0)


# ── Work Order schemas ───────────────────────────────────────────────────────


class WorkOrderCreate(BaseModel):
    """Create a new work order.

    v3 §10 - ``planned_cost`` / ``actual_cost`` are money;
    Decimal-as-string in JSON.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    activity_id: UUID = Field(default=None)  # type: ignore[assignment]
    assembly_id: UUID | None = None
    boq_position_id: UUID | None = None
    code: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=5000)
    assigned_to: str = Field(default="", max_length=255)
    planned_start: str | None = Field(default=None, max_length=20)
    planned_end: str | None = Field(default=None, max_length=20)
    actual_start: str | None = Field(default=None, max_length=20)
    actual_end: str | None = Field(default=None, max_length=20)
    planned_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1e12"))
    actual_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1e12"))
    status: str = Field(
        default="planned",
        pattern=r"^(planned|issued|in_progress|completed|cancelled)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("planned_cost", "actual_cost", mode="after")
    @classmethod
    def _reject_non_finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("cost must be finite (no NaN / Infinity)")
        return v

    @field_serializer("planned_cost", "actual_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class WorkOrderUpdate(BaseModel):
    """Partial update for a work order."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    assembly_id: UUID | None = None
    boq_position_id: UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    assigned_to: str | None = Field(default=None, max_length=255)
    planned_start: str | None = Field(default=None, max_length=20)
    planned_end: str | None = Field(default=None, max_length=20)
    actual_start: str | None = Field(default=None, max_length=20)
    actual_end: str | None = Field(default=None, max_length=20)
    planned_cost: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"))
    actual_cost: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"))
    status: str | None = Field(
        default=None,
        pattern=r"^(planned|issued|in_progress|completed|cancelled)$",
    )
    metadata: dict[str, Any] | None = None

    @field_validator("planned_cost", "actual_cost", mode="after")
    @classmethod
    def _reject_non_finite(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("cost must be finite (no NaN / Infinity)")
        return v

    @field_serializer("planned_cost", "actual_cost", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class WorkOrderStatusUpdate(BaseModel):
    """Request body for updating work order status."""

    status: str = Field(..., pattern=r"^(planned|issued|in_progress|completed|cancelled)$")


class WorkOrderResponse(BaseModel):
    """Work order returned from the API.

    v3 §10 - ``planned_cost`` / ``actual_cost`` are money;
    Decimal-as-string in JSON.
    """

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
    planned_cost: Decimal = Decimal("0")
    actual_cost: Decimal = Decimal("0")
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("planned_cost", "actual_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Composite schemas ────────────────────────────────────────────────────────


class ScheduleWithActivities(ScheduleResponse):
    """Schedule with all its activities."""

    activities: list[ActivityResponse] = Field(default_factory=list)


class GanttActivity(BaseModel):
    """Single activity formatted for Gantt chart rendering."""

    id: UUID
    name: str
    start_date: str
    end_date: str
    duration_days: int = 0
    progress_pct: float
    dependencies: list[dict[str, Any]]
    parent_id: UUID | None
    color: str
    boq_position_ids: list[str]
    wbs_code: str
    activity_type: str
    status: str
    # Per-activity work calendar (schedule_advanced Calendar), so the grid's
    # calendar picker can show and clear the current assignment. None -> the
    # activity uses the schedule default.
    calendar_id: UUID | None = None
    # Activity metadata passthrough. Generated activities carry provenance
    # markers here (e.g. duration_source/duration_method = "estimated_fallback"
    # when the duration was estimated from unit-based production rates), which
    # the frontend surfaces as an "estimated duration" hint.
    metadata: dict[str, Any] = Field(default_factory=dict)


class GanttSummary(BaseModel):
    """Summary statistics for a Gantt chart."""

    total_activities: int = 0
    completed: int = 0
    in_progress: int = 0
    delayed: int = 0
    not_started: int = 0


class NextMilestone(BaseModel):
    """The next milestone to watch on a project's schedule."""

    name: str
    date: str = Field(description="ISO planned date (YYYY-MM-DD) of the milestone")


class ScheduleStatsResponse(BaseModel):
    """Aggregate schedule statistics for a project's schedules and activities."""

    total_activities: int = 0
    critical_count: int = Field(default=0, description="Activities on the critical path (is_critical=True)")
    on_track: int = Field(
        default=0, description="Activities with status not_started or in_progress that are not delayed"
    )
    delayed: int = Field(default=0, description="Activities with status=delayed")
    completed: int = 0
    not_started: int = 0
    in_progress: int = 0
    progress_pct: float = Field(
        default=0.0,
        description="Overall weighted progress across all activities (0.0 - 100.0)",
    )
    total_duration_days: int = Field(
        default=0,
        description="Sum of all activity durations",
    )
    next_milestone: NextMilestone | None = Field(
        default=None,
        description="Earliest unfinished milestone (upcoming preferred, else most overdue)",
    )


class WorkCalendarResponse(BaseModel):
    """Resolved regional work calendar for a project.

    Returns the calendar the backend actually uses for duration/CPM math, so the
    frontend renders the true hours-per-day / days-per-week instead of
    re-deriving it from a smaller client-side map that can diverge.
    """

    region: str | None = Field(default=None, description="The project region the calendar was resolved from")
    hours_per_day: float = Field(description="Working hours per day")
    work_days_per_week: int = Field(description="Number of working days per week")
    label: str = Field(description="Human-readable calendar label")


class ClearActivitiesResponse(BaseModel):
    """Result of a bulk activity clear (schedule reset)."""

    schedule_id: UUID
    deleted: int = Field(description="Number of activities removed")


class GanttData(BaseModel):
    """Structured data for Gantt chart rendering."""

    activities: list[GanttActivity] = Field(default_factory=list)
    summary: GanttSummary = Field(default_factory=GanttSummary)


# ── CPM & Risk Analysis schemas ─────────────────────────────────────────────


class GenerateFromBOQRequest(BaseModel):
    """Request body for generating schedule activities from a BOQ."""

    model_config = ConfigDict(extra="ignore")

    boq_id: UUID
    total_project_days: int | None = Field(
        default=None,
        ge=1,
        le=_MAX_SCHEDULE_DAYS,
        description=(
            "Total project duration in calendar days. "
            "If omitted, defaults to 365 (residential) or 540 (office) based on BOQ metadata."
        ),
    )


class CPMActivityResult(BaseModel):
    """CPM calculation results for a single activity."""

    activity_id: UUID
    name: str
    duration_days: int
    early_start: int = Field(description="Early start day (0-based from project start)")
    early_finish: int = Field(description="Early finish day")
    late_start: int = Field(description="Late start day")
    late_finish: int = Field(description="Late finish day")
    total_float: int = Field(description="Total float (LS - ES). 0 = critical.")
    is_critical: bool


class CriticalPathResponse(BaseModel):
    """Response from CPM calculation."""

    schedule_id: UUID
    project_duration_days: int = Field(description="Total project duration from CPM")
    critical_path: list[CPMActivityResult] = Field(description="Activities on the critical path (float = 0)")
    all_activities: list[CPMActivityResult] = Field(description="All activities with CPM data")


class RiskAnalysisResponse(BaseModel):
    """PERT-based risk analysis response."""

    schedule_id: UUID
    deterministic_days: int = Field(description="Deterministic project duration from CPM")
    p50_days: int = Field(description="50th percentile duration estimate")
    p80_days: int = Field(description="80th percentile duration estimate")
    p95_days: int = Field(description="95th percentile duration estimate")
    mean_days: float = Field(description="Expected (mean) duration")
    std_dev_days: float = Field(description="Standard deviation in days")
    risk_buffer_days: int = Field(description="Recommended buffer (P80 - deterministic)")
    activity_risks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-activity PERT estimates (optimistic, most_likely, pessimistic)",
    )


# ── Import/Export schemas ───────���─────────────────────────────────────────


class ImportResult(BaseModel):
    """Result from importing a schedule file (XER / MSP XML)."""

    activities_imported: int = 0
    relationships_imported: int = 0
    calendars_imported: int = 0
    warnings: list[str] = Field(default_factory=list)


# ── Schedule Relationship schemas (Phase 13) ──────────────────────────────


class RelationshipCreate(BaseModel):
    """Create a CPM dependency relationship between two activities."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    predecessor_id: UUID
    successor_id: UUID
    relationship_type: str = Field(default="FS", pattern=r"^(FS|FF|SS|SF)$")
    # Negative lag allowed (lead time); bound both sides at int32.
    lag_days: int = Field(default=0, ge=-_INT32_MAX, le=_INT32_MAX)


class RelationshipUpdate(BaseModel):
    """Partial update of a CPM dependency relationship.

    Only the type and/or lag of an existing edge may change; the endpoints
    (predecessor / successor) are immutable - re-pointing an edge is a
    delete + create so the self-reference and cycle guards run against the
    new endpoints. Both fields are optional so a caller can PATCH just one.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    relationship_type: Literal["FS", "FF", "SS", "SF"] | None = None
    # Negative lag allowed (lead time); bound both sides at int32.
    lag_days: int | None = Field(default=None, ge=-_INT32_MAX, le=_INT32_MAX)


class RelationshipResponse(BaseModel):
    """Schedule relationship returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    schedule_id: UUID
    predecessor_id: UUID
    successor_id: UUID
    relationship_type: str
    lag_days: int
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class CPMCalculateRequest(BaseModel):
    """Request body for CPM calculation with optional work calendar override.

    The calendar here is the engine's second entrance, and until now the only
    unguarded one. It is passed straight to :func:`app.core.cpm.calculate_cpm`
    without touching the schedule's stored metadata, so the check on that field
    never saw it, and the endpoint persists what it computes onto every
    activity. An override the engine cannot read therefore wrote wrong dates to
    the database and returned success.
    """

    calendar: dict[str, Any] | None = Field(
        default=None,
        description="Work calendar override: {work_days: [0-4], exceptions: []}",
    )

    @field_validator("calendar")
    @classmethod
    def _check_calendar(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Apply the shared override rules to the request body's calendar.

        Unlike the calendar write schemas, this field is typed ``dict[str, Any]``,
        so ``str_strip_whitespace`` does not reach the strings inside it. An
        entry pasted with a leading space arrives here untrimmed and is
        normalised by the shared check rather than by the model config.
        """
        if isinstance(v, dict):
            _check_calendar_override(v, source="calendar")
        return v


# ── Schedule Baseline schemas ──────────────────────────────────────────────


class BaselineCreate(BaseModel):
    """Create a schedule baseline snapshot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schedule_id: UUID | None = None
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    baseline_date: str = Field(..., max_length=20)
    snapshot_data: dict[str, Any] = Field(..., description="Complete snapshot of activities")
    is_active: bool = True
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaselineUpdate(BaseModel):
    """Partial update for a schedule baseline.

    Baselines are snapshot-in-time records - ``name``, ``baseline_date``
    and ``snapshot_data`` are immutable by design. ``is_active`` stays
    writable because it's a workflow flag (which baseline is "current"
    for EVM comparisons), not a property of the snapshot itself.
    Renames, if ever needed for typo fixes, go through a dedicated
    admin-only endpoint; they are not allowed here.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    is_active: bool | None = None


class BaselineResponse(BaseModel):
    """Schedule baseline returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    schedule_id: UUID | None
    project_id: UUID
    name: str
    baseline_date: str
    snapshot_data: dict[str, Any]
    is_active: bool
    created_by: UUID | None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Progress Update schemas ────────────────────────────────────────────────


class ProgressUpdateCreate(BaseModel):
    """Create a progress update record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    activity_id: UUID | None = None
    update_date: str = Field(..., max_length=20)
    progress_pct: str | None = Field(default=None, max_length=10)
    actual_start: str | None = Field(default=None, max_length=20)
    actual_finish: str | None = Field(default=None, max_length=20)
    remaining_duration: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=5000)
    status: str = Field(
        default="draft",
        pattern=r"^(draft|submitted|approved)$",
    )
    submitted_by: UUID | None = None
    approved_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProgressUpdateEdit(BaseModel):
    """Partial update for a progress update record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    progress_pct: str | None = Field(default=None, max_length=10)
    actual_start: str | None = Field(default=None, max_length=20)
    actual_finish: str | None = Field(default=None, max_length=20)
    remaining_duration: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|submitted|approved)$",
    )
    submitted_by: UUID | None = None
    approved_by: UUID | None = None
    metadata: dict[str, Any] | None = None


class ProgressUpdateResponse(BaseModel):
    """Progress update record returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    activity_id: UUID | None
    update_date: str
    progress_pct: str | None
    actual_start: str | None
    actual_finish: str | None
    remaining_duration: str | None
    notes: str | None
    status: str
    submitted_by: UUID | None
    approved_by: UUID | None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Project Intelligence (RFC 25) ───────────────────────────────────────────


class LaborCostByPhaseRow(BaseModel):
    """Rolled-up labour cost for a single schedule phase / WBS group.

    v3 §10 - ``labor_cost`` and ``total_cost`` are money;
    Decimal-as-string in JSON.
    """

    phase: str = Field("", description="Phase label - wbs_code prefix or activity_type")
    activity_count: int = 0
    labor_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    start_date: str | None = None
    end_date: str | None = None

    @field_serializer("labor_cost", "total_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class LaborCostByPhaseResponse(BaseModel):
    """Container for the labour-cost-by-phase stacked area chart."""

    phases: list[LaborCostByPhaseRow] = Field(default_factory=list)
    # Currency bug fix: default to blank ("unknown"), NOT a hardcoded "EUR".
    # All labour/total costs here are project-scoped so they share one ISO
    # currency; the service populates this with the project's real currency
    # (Project.currency). A blank fallback signals "unknown" rather than
    # silently mislabelling BRL/GBP/USD amounts as EUR.
    currency: str = ""


# ── EVM summary (Section 6 - earned-value rollup) ───────────────────────────


class EvmSummaryResponse(BaseModel):
    """Scalar earned-value metrics for a schedule at a data date.

    Mirrors :class:`app.modules.schedule.service_4d.EvmSummary`. Money fields
    are emitted as Decimal-as-string (the platform money wire contract the
    frontend ``shared/lib/money.ts`` decodes); the dimensionless performance
    indices (``spi`` / ``cpi``) and the forecast block (``estimate_at_*`` /
    ``variance_at_completion``) are ``float | None`` - ``None`` when the
    schedule is not cost-loaded or a denominator is zero (division by zero is
    undefined, surfaced to the UI as "not available" rather than a bogus 0).
    """

    schedule_id: UUID
    as_of_date: str
    #: ISO 4217 code every money field below is denominated in, and the code
    #: they were rounded to. Blank when the project has no currency set. It is
    #: not decoration: without it a reader cannot tell an integer yen amount
    #: from an amount that lost its decimals somewhere.
    currency: str = ""
    # ── Cost-loaded money fields (Decimal-as-string) ──────────────────────
    planned_value: Decimal = Decimal("0")  # PV / BCWS, time-phased to as_of
    earned_value: Decimal = Decimal("0")  # EV / BCWP
    actual_cost: Decimal = Decimal("0")  # AC / ACWP
    budget_at_completion: Decimal = Decimal("0")  # BAC = sum of cost_planned
    schedule_variance: Decimal = Decimal("0")  # SV = EV - PV
    cost_variance: Decimal = Decimal("0")  # CV = EV - AC
    estimate_at_completion: Decimal | None = None  # EAC = BAC / CPI
    estimate_to_complete: Decimal | None = None  # ETC = EAC - AC
    variance_at_completion: Decimal | None = None  # VAC = BAC - EAC
    # ── Dimensionless performance indices ─────────────────────────────────
    spi: float | None = None  # SPI = EV / PV
    cpi: float | None = None  # CPI = EV / AC
    has_cost_data: bool = False

    @field_serializer(
        "planned_value",
        "earned_value",
        "actual_cost",
        "budget_at_completion",
        "schedule_variance",
        "cost_variance",
        "estimate_at_completion",
        "estimate_to_complete",
        "variance_at_completion",
        when_used="json",
    )
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


# ── Schedule comparison / diff (T1.3) ────────────────────────────────────────


class SnapshotEnvelopeResponse(BaseModel):
    """The live schedule flattened into the canonical diff envelope.

    Returned by ``GET /schedules/{id}/snapshot-envelope`` so a client can
    capture the current state (e.g. store it as a baseline) and later diff two
    envelopes. The ``envelope`` is opaque to the API and consumed verbatim by
    the diff engine.
    """

    schedule_id: UUID
    envelope: dict[str, Any] = Field(default_factory=dict)


class ScheduleDiffRequest(BaseModel):
    """Body for ``POST /schedules/{id}/diff``.

    The *base* side is required: either a captured baseline (``base_baseline_id``)
    or an envelope posted inline (``base_envelope``). The *target* side defaults
    to the live schedule, or another baseline via ``target_baseline_id``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    base_baseline_id: UUID | None = None
    base_envelope: dict[str, Any] | None = None
    target_baseline_id: UUID | None = None


class DiffActivityChangeSchema(BaseModel):
    """One activity added, removed or modified between the two snapshots."""

    key: str
    change_type: str
    categories: list[str] = Field(default_factory=list)
    fields: dict[str, dict[str, Any]] = Field(default_factory=dict)
    finish_movement_days: int = 0
    critical_path: bool = False
    name: str | None = None
    wbs_code: str | None = None


class DiffRelationshipChangeSchema(BaseModel):
    """One dependency link added, removed, retyped or re-lagged."""

    key: list[str] = Field(default_factory=list)
    change_type: str
    categories: list[str] = Field(default_factory=list)
    fields: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DiffCalendarChangeSchema(BaseModel):
    """One calendar added, removed or whose definition changed."""

    key: str
    change_type: str
    categories: list[str] = Field(default_factory=list)


class DiffSummarySchema(BaseModel):
    """Roll-up metrics across the whole diff."""

    net_finish_movement_days: int = 0
    count_by_category: dict[str, int] = Field(default_factory=dict)
    activities_added: int = 0
    activities_removed: int = 0
    activities_changed: int = 0
    relationships_added: int = 0
    relationships_removed: int = 0
    relationships_retyped: int = 0
    relationships_relagged: int = 0
    critical_path_in: int = 0
    critical_path_out: int = 0
    cost_planned_delta: str = "0"
    cost_actual_delta: str = "0"
    largest_slips: list[dict[str, Any]] = Field(default_factory=list)


class ScheduleDiffResponse(BaseModel):
    """Response for ``POST /schedules/{id}/diff`` - the categorized diff."""

    schedule_id: UUID
    base_label: str = ""
    target_label: str = ""
    activities: list[DiffActivityChangeSchema] = Field(default_factory=list)
    relationships: list[DiffRelationshipChangeSchema] = Field(default_factory=list)
    calendars: list[DiffCalendarChangeSchema] = Field(default_factory=list)
    summary: DiffSummarySchema = Field(default_factory=DiffSummarySchema)
