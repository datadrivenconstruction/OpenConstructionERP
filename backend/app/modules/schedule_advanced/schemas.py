# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Advanced Pydantic schemas - request / response models.

Covers all 10 LPS entities plus aggregate response schemas for the
LPS dashboard, PPC chart, RNC pareto, baseline delta, and look-ahead.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.cpm import MAX_WEEKDAY, MIN_WEEKDAY
from app.modules.schedule_advanced.cpm import normalise_holidays

# ── Common patterns ────────────────────────────────────────────────────────


# Money fields are accepted as ``Decimal`` and emitted as plain decimal
# *strings* in JSON (v3 §10): floats lose precision past ~15 sig figs and force
# every consumer to parse a locale-coloured number. Canonical helper mirrored
# from ``boq.schemas._serialise_money`` - keep the siblings in sync.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (ArithmeticError, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


_PHASE_STATUS = r"^(in_planning|pulled|active|completed)$"
_LOOK_AHEAD_STATUS = r"^(draft|reviewed|published)$"
_CONSTRAINT_TYPE = r"^(info|material|labor|equipment|permit|predecessor|weather|other)$"
_CONSTRAINT_STATUS = r"^(open|in_progress|cleared|escalated|cannot_clear)$"
_COMMITMENT_STATUS = r"^(planned|committed|in_progress|completed|at_risk|missed)$"
_WEEKLY_STATUS = r"^(draft|committed|in_progress|closed)$"
_BASELINE_STATUS = r"^(active|superseded|archived)$"
_MASTER_STATUS = r"^(active|archived)$"
_RNC_CATEGORY = r"^(manpower|material|equipment|info|weather|predecessor|changes|quality|other)$"


# ── MasterSchedule ─────────────────────────────────────────────────────────


class MasterScheduleCreate(BaseModel):
    """Create a new master schedule for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    baseline_date: date | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    status: str = Field(default="active", pattern=_MASTER_STATUS)
    notes: str = ""


class MasterScheduleUpdate(BaseModel):
    """Patch update for a master schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    baseline_date: date | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    status: str | None = Field(default=None, pattern=_MASTER_STATUS)
    notes: str | None = None


class MasterScheduleResponse(BaseModel):
    """Master schedule returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    baseline_date: date | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    status: str = "active"
    notes: str = ""
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── PhasePlan ──────────────────────────────────────────────────────────────


class PhasePlanCreate(BaseModel):
    """Create a new phase plan inside a pull session."""

    model_config = ConfigDict(str_strip_whitespace=True)

    master_schedule_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    planned_start: date | None = None
    planned_finish: date | None = None
    milestone_target_id: UUID | None = None
    pulled_status: str = Field(default="in_planning", pattern=_PHASE_STATUS)
    pull_session_at: datetime | None = None
    facilitator_id: UUID | None = None
    notes: str = ""


class PhasePlanUpdate(BaseModel):
    """Patch update for a phase plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    planned_start: date | None = None
    planned_finish: date | None = None
    milestone_target_id: UUID | None = None
    pulled_status: str | None = Field(default=None, pattern=_PHASE_STATUS)
    pull_session_at: datetime | None = None
    facilitator_id: UUID | None = None
    notes: str | None = None


class PhasePlanResponse(BaseModel):
    """Phase plan returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    master_schedule_id: UUID
    name: str
    planned_start: date | None = None
    planned_finish: date | None = None
    milestone_target_id: UUID | None = None
    pulled_status: str = "in_planning"
    pull_session_at: datetime | None = None
    facilitator_id: UUID | None = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime


# ── LookAheadPlan ──────────────────────────────────────────────────────────


class LookAheadCreate(BaseModel):
    """Create a new look-ahead plan window."""

    model_config = ConfigDict(str_strip_whitespace=True)

    master_schedule_id: UUID
    period_start: date
    period_end: date
    window_weeks: int = Field(default=6, ge=1, le=24)
    generated_at: datetime | None = None
    status: str = Field(default="draft", pattern=_LOOK_AHEAD_STATUS)


class LookAheadUpdate(BaseModel):
    """Patch update for a look-ahead plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    period_start: date | None = None
    period_end: date | None = None
    window_weeks: int | None = Field(default=None, ge=1, le=24)
    generated_at: datetime | None = None
    status: str | None = Field(default=None, pattern=_LOOK_AHEAD_STATUS)


class LookAheadResponse(BaseModel):
    """Look-ahead plan returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    master_schedule_id: UUID
    period_start: date
    period_end: date
    window_weeks: int = 6
    generated_at: datetime | None = None
    status: str = "draft"
    created_at: datetime
    updated_at: datetime


# ── Constraint ─────────────────────────────────────────────────────────────


class ConstraintCreate(BaseModel):
    """Create a constraint blocking a task."""

    model_config = ConfigDict(str_strip_whitespace=True)

    look_ahead_id: UUID | None = None
    task_ref: UUID
    constraint_type: str = Field(..., pattern=_CONSTRAINT_TYPE)
    description: str = ""
    owner_user_id: UUID | None = None
    target_clear_date: date | None = None
    status: str = Field(default="open", pattern=_CONSTRAINT_STATUS)
    linked_type: str | None = Field(default=None, pattern=r"^(rfi|submittal|purchase_order|goods_receipt)$")
    linked_id: UUID | None = None


class ConstraintUpdate(BaseModel):
    """Patch update for a constraint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    look_ahead_id: UUID | None = None
    constraint_type: str | None = Field(default=None, pattern=_CONSTRAINT_TYPE)
    description: str | None = None
    owner_user_id: UUID | None = None
    target_clear_date: date | None = None
    cleared_at: datetime | None = None
    cleared_by: UUID | None = None
    status: str | None = Field(default=None, pattern=_CONSTRAINT_STATUS)
    linked_type: str | None = Field(default=None, pattern=r"^(rfi|submittal|purchase_order|goods_receipt)$")
    linked_id: UUID | None = None


class ConstraintResponse(BaseModel):
    """Constraint returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    look_ahead_id: UUID | None = None
    task_ref: UUID
    constraint_type: str
    description: str = ""
    owner_user_id: UUID | None = None
    target_clear_date: date | None = None
    cleared_at: datetime | None = None
    cleared_by: UUID | None = None
    status: str = "open"
    linked_type: str | None = None
    linked_id: UUID | None = None
    link_resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── WeeklyWorkPlan ─────────────────────────────────────────────────────────


class WeeklyWorkPlanCreate(BaseModel):
    """Create a weekly work plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    master_schedule_id: UUID
    week_start_date: date
    week_end_date: date
    facilitator_id: UUID | None = None
    status: str = Field(default="draft", pattern=_WEEKLY_STATUS)
    notes: str = ""


class WeeklyWorkPlanUpdate(BaseModel):
    """Patch update for a weekly work plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    week_start_date: date | None = None
    week_end_date: date | None = None
    facilitator_id: UUID | None = None
    status: str | None = Field(default=None, pattern=_WEEKLY_STATUS)
    notes: str | None = None


class WeeklyWorkPlanResponse(BaseModel):
    """Weekly work plan returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    master_schedule_id: UUID
    week_start_date: date
    week_end_date: date
    generated_at: datetime | None = None
    facilitator_id: UUID | None = None
    status: str = "draft"
    ppc_percent: Decimal | None = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime


# ── Commitment ─────────────────────────────────────────────────────────────


class CommitmentCreate(BaseModel):
    """Create a commitment (promise) for a weekly work plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    week_plan_id: UUID
    task_ref: UUID
    worker_or_crew: str = ""
    promised_qty: Decimal = Decimal("0")
    unit: str = ""
    planned_start: date | None = None
    planned_finish: date | None = None
    status: str = Field(default="planned", pattern=_COMMITMENT_STATUS)
    made_by_user_id: UUID | None = None
    made_at: datetime | None = None
    subcontractor_id: UUID | None = None
    target_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)


class CommitmentUpdate(BaseModel):
    """Patch update for a commitment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    worker_or_crew: str | None = None
    promised_qty: Decimal | None = None
    unit: str | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    status: str | None = Field(default=None, pattern=_COMMITMENT_STATUS)
    actual_qty: Decimal | None = None
    completed_at: datetime | None = None
    subcontractor_id: UUID | None = None
    target_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)


class CommitmentResponse(BaseModel):
    """Commitment returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    week_plan_id: UUID
    task_ref: UUID
    worker_or_crew: str = ""
    promised_qty: Decimal = Decimal("0")
    unit: str = ""
    planned_start: date | None = None
    planned_finish: date | None = None
    status: str = "planned"
    made_by_user_id: UUID | None = None
    made_at: datetime | None = None
    completed_at: datetime | None = None
    actual_qty: Decimal | None = None
    subcontractor_id: UUID | None = None
    target_progress_pct: Decimal | None = None
    created_at: datetime
    updated_at: datetime


# ── ReasonForNonCompletion ─────────────────────────────────────────────────


class RNCCreate(BaseModel):
    """Record a reason a commitment was not completed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    commitment_id: UUID
    category: str = Field(..., pattern=_RNC_CATEGORY)
    description: str = ""
    recorded_at: datetime | None = None
    root_cause_notes: str = ""


class RNCUpdate(BaseModel):
    """Patch update for an RNC."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(default=None, pattern=_RNC_CATEGORY)
    description: str | None = None
    root_cause_notes: str | None = None


class RNCResponse(BaseModel):
    """RNC returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    commitment_id: UUID
    category: str
    description: str = ""
    recorded_at: datetime | None = None
    recorded_by: UUID | None = None
    root_cause_notes: str = ""
    created_at: datetime
    updated_at: datetime


# ── Baseline ───────────────────────────────────────────────────────────────


class BaselineCreate(BaseModel):
    """Create a baseline by capturing the current schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    master_schedule_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    snapshot: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    status: str = Field(default="active", pattern=_BASELINE_STATUS)


class BaselineUpdate(BaseModel):
    """Patch update for a baseline."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    status: str | None = Field(default=None, pattern=_BASELINE_STATUS)


class BaselineResponse(BaseModel):
    """Baseline returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    master_schedule_id: UUID
    name: str
    captured_at: datetime | None = None
    captured_by: UUID | None = None
    snapshot: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    status: str = "active"
    created_at: datetime
    updated_at: datetime


# ── BaselineDelta ──────────────────────────────────────────────────────────


class BaselineDeltaEntry(BaseModel):
    """One row in the baseline-vs-current variance comparison."""

    task_ref: UUID
    planned_start_baseline: date | None = None
    planned_start_current: date | None = None
    planned_finish_baseline: date | None = None
    planned_finish_current: date | None = None
    schedule_variance_days: int = 0
    # Carried through from the snapshot row when present (e.g. phase plans
    # captured via the front-end's ``captureBaseline`` helper include the
    # phase name). Lets the UI render "Foundation +5d" instead of a raw
    # UUID. Optional + tolerant so legacy snapshots without ``name`` keep
    # validating cleanly.
    name: str | None = None


class BaselineDeltaResponse(BaseModel):
    """Result of a baseline delta computation."""

    baseline_id: UUID
    current_master_id: UUID
    entries: list[BaselineDeltaEntry] = Field(default_factory=list)
    total_tasks: int = 0
    delayed_tasks: int = 0
    accelerated_tasks: int = 0


# ── Calendar ───────────────────────────────────────────────────────────────

# Monday-zero weekday numbers, Monday = 0 through Sunday = 6. That is what this
# module's ``Calendar`` stores and what ``app.core.cpm`` counts with, because it
# matches each date's ``date.weekday()`` against this list.
#
# A 7 here is the mirror of the defect that shipped in the ISO work calendar. It
# is not a weekday under this reading, so ``app.core.cpm`` drops it, and if that
# empties the week the engine falls back to Monday-Friday - deliberately, to keep
# its day-stepping loops terminating. The schedule is then computed against a week
# nobody asked for and nothing raises. That tolerance is load-bearing and stays;
# the refusal belongs here, on the way in, where a caller can still be told.
#
# ``app/core/cpm.py`` already records ``work_days=[7]`` as "a common Sunday = ISO 7
# mistake", so this is a mistake that has been met rather than one imagined. Sunday
# is 6 in this convention. The platform's other work calendar - the i18n
# ``WorkCalendar`` - is ISO, Monday = 1 through Sunday = 7. Neither is this one.
#
# The bounds come from the engine rather than being restated here, so the range a
# writer refuses and the range the engine counts cannot drift apart.
Mon0Weekday = Annotated[int, Field(ge=MIN_WEEKDAY, le=MAX_WEEKDAY)]


def _canonical_holidays(value: list[str] | None) -> list[str] | None:
    """Store each holiday in the one spelling every reader can match.

    ``work_days`` beside it has been constrained since the Monday-zero
    convention was settled, and ``holidays`` was not, so this model refused a
    week running to eight days while accepting a holiday written 01/05/2026.
    That entry is stored, read by three different consumers, matched by none of
    them, and worked as an ordinary day without anything being logged.

    Refusing at the write is what makes that visible, because it is the last
    moment the writer is present to be told. It is deliberately not a refusal
    of untidy input: a date pasted from a spreadsheet or written by an export
    is accepted and canonicalised, and only a value naming no single day is
    turned away.
    """
    if value is None:
        return None
    return normalise_holidays(value)


class CalendarCreate(BaseModel):
    """Create a working calendar."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    work_days: list[Mon0Weekday] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    work_hours_per_day: Decimal = Decimal("8")
    holidays: list[str] = Field(default_factory=list)
    special_shifts: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False

    _normalise_holidays = field_validator("holidays")(_canonical_holidays)


class CalendarUpdate(BaseModel):
    """Patch update for a calendar."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    work_days: list[Mon0Weekday] | None = None
    work_hours_per_day: Decimal | None = None
    holidays: list[str] | None = None
    special_shifts: dict[str, Any] | None = None
    is_default: bool | None = None

    _normalise_holidays = field_validator("holidays")(_canonical_holidays)


class CalendarResponse(BaseModel):
    """Calendar returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    # Deliberately unconstrained, unlike the write schemas above: a calendar
    # stored before the guard existed still has to be readable, and refusing to
    # serialise it would hide the very row an operator needs to see to fix.
    work_days: list[int] = Field(default_factory=list)
    work_hours_per_day: Decimal = Decimal("8")
    holidays: list[str] = Field(default_factory=list)
    special_shifts: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


# ── Aggregate / dashboard responses ────────────────────────────────────────


class PPCResponse(BaseModel):
    """Percent Plan Complete result for one week or aggregate."""

    week_start_date: date | None = None
    total_commitments: int = 0
    completed_commitments: int = 0
    ppc_percent: Decimal = Decimal("0")


class RNCParetoResponse(BaseModel):
    """RNC pareto distribution by category."""

    period_start: date
    period_end: date
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class LPSDashboardResponse(BaseModel):
    """Aggregated LPS dashboard for one project."""

    project_id: UUID
    ppc_trend: list[PPCResponse] = Field(default_factory=list)
    open_constraints: int = 0
    constraints_by_type: dict[str, int] = Field(default_factory=dict)
    rnc_pareto: dict[str, int] = Field(default_factory=dict)
    active_master_schedules: int = 0
    active_baselines: int = 0
    current_week_commitments: int = 0


# ── CPM / EVM / TIA ────────────────────────────────────────────────────────


class CPMActivityInput(BaseModel):
    """One activity for the /cpm endpoint.

    ``predecessors`` is a list of activity ids that must finish before this
    activity can start (FS relationships). Use the top-level
    ``dependencies`` array on :class:`CPMRequest` for cleaner modelling.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(default="", max_length=255)
    duration: int = Field(default=0, ge=0)
    predecessors: list[str] = Field(default_factory=list)


class CPMDependencyInput(BaseModel):
    """One FS edge between two activities."""

    model_config = ConfigDict(str_strip_whitespace=True)

    predecessor: str
    successor: str


class CPMRequest(BaseModel):
    """Payload for /cpm - runs forward + backward pass."""

    model_config = ConfigDict(str_strip_whitespace=True)

    activities: list[CPMActivityInput]
    dependencies: list[CPMDependencyInput] | None = None


class CPMActivityResult(BaseModel):
    """Per-activity CPM result."""

    id: str
    es: int = 0
    ef: int = 0
    ls: int = 0
    lf: int = 0
    total_float: int = 0
    free_float: int = 0
    is_critical: bool = False
    duration: int = 0


class CPMResponse(BaseModel):
    """Response from /cpm - per-activity schedule + project finish."""

    project_finish_workday: int = 0
    critical_path_count: int = 0
    activities: list[CPMActivityResult] = Field(default_factory=list)


class TIARequest(BaseModel):
    """Payload for /tia - time-impact-analysis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    activities: list[CPMActivityInput]
    dependencies: list[CPMDependencyInput] | None = None
    impacted_activity_id: str
    delay_days: int = Field(..., ge=0)


class TIAResponse(BaseModel):
    """Response from /tia - schedule slip + critical-path drift."""

    original_finish_workday: int = 0
    impacted_finish_workday: int = 0
    delta_days: int = 0
    newly_critical_activity_ids: list[str] = Field(default_factory=list)
    no_longer_critical_activity_ids: list[str] = Field(default_factory=list)


class EVMActivityInput(BaseModel):
    """One activity for the /evm endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., min_length=1, max_length=80)
    budget_at_completion: Decimal = Decimal("0")
    percent_complete: Decimal = Decimal("0")
    actual_cost: Decimal = Decimal("0")
    planned_start_workday: int = 0
    planned_finish_workday: int = 0


class EVMRequest(BaseModel):
    """Payload for /evm - earned value computation at a given workday."""

    model_config = ConfigDict(str_strip_whitespace=True)

    activities: list[EVMActivityInput]
    today_workday: int = Field(..., ge=0)


class EVMResponse(BaseModel):
    """Response from /evm - full EVM dashboard."""

    bac: Decimal = Decimal("0")
    pv: Decimal = Decimal("0")
    ev: Decimal = Decimal("0")
    ac: Decimal = Decimal("0")
    spi: Decimal = Decimal("0")
    cpi: Decimal = Decimal("0")
    eac: Decimal = Decimal("0")
    etc: Decimal = Decimal("0")
    vac: Decimal = Decimal("0")
    sv: Decimal = Decimal("0")
    cv: Decimal = Decimal("0")


class RNCParetoRow(BaseModel):
    """One row in the sorted Pareto chart."""

    category: str
    count: int = 0
    percent: float = 0.0
    cum_percent: float = 0.0


class RNCParetoSortedResponse(BaseModel):
    """Response for the sorted Pareto endpoint."""

    period_start: date
    period_end: date
    rows: list[RNCParetoRow] = Field(default_factory=list)
    total: int = 0


class ConstraintReadinessBlocker(BaseModel):
    """One open constraint blocking a task."""

    id: str
    type: str
    description: str = ""
    owner_user_id: str | None = None
    target_clear_date: str | None = None


class ConstraintReadinessResponse(BaseModel):
    """Per-task readiness summary for a Look-Ahead screen."""

    task_ref: str
    is_ready: bool = True
    open_count: int = 0
    blockers: list[ConstraintReadinessBlocker] = Field(default_factory=list)


# ── CPM Slice 1 - persisted compute + leveling + weekly commitments ────────


class CPMComputeSummary(BaseModel):
    """Summary returned by ``POST /schedule-advanced/{schedule_id}/compute-cpm``.

    The per-activity ES/EF/LS/LF/total_float/is_critical values are written
    back onto the schedule's :class:`Activity` rows; only the aggregate
    summary travels over the wire.
    """

    schedule_id: UUID
    critical_path: list[UUID] = Field(default_factory=list)
    project_duration_days: int = 0
    num_critical: int = 0
    num_activities: int = 0


class LevelResourcesRequest(BaseModel):
    """Body for ``POST /schedule-advanced/{schedule_id}/level-resources``.

    ``resource_limits`` is a mapping of resource code → max concurrent
    units. Resources omitted from the dict are unconstrained.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    resource_limits: dict[str, int] = Field(default_factory=dict)


class LevelResourcesShift(BaseModel):
    """One activity-shift row produced by resource leveling."""

    activity_id: UUID
    original_es: int = 0
    shifted_es: int = 0
    delta_days: int = 0


class LevelResourcesUnresolvable(BaseModel):
    """An activity whose own demand exceeds a ceiling on its own."""

    activity_id: UUID
    resource: str
    required: float
    limit: float


class LevelResourcesResponse(BaseModel):
    """Response for /level-resources - only changed activities listed."""

    schedule_id: UUID
    shifts: list[LevelResourcesShift] = Field(default_factory=list)
    num_shifted: int = 0
    # Shifting cannot clear an overload one activity causes by itself, so such
    # an activity is placed at its earliest legal start and named here. Without
    # this list it would be absent from `shifts` and read exactly like an
    # activity that needed no shift, while its ceiling stays breached.
    unresolvable: list[LevelResourcesUnresolvable] = Field(default_factory=list)


class WeeklyCommitmentCreate(BaseModel):
    """Body for ``POST /schedule-advanced/{schedule_id}/commitments``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    activity_id: UUID
    week_start: date
    planned_complete_pct: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    actual_complete_pct: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class WeeklyCommitmentResponse(BaseModel):
    """Stored weekly commitment row with auto-computed PPC."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    schedule_id: UUID
    activity_id: UUID
    week_start: date
    committed_by: UUID | None = None
    planned_complete_pct: Decimal = Decimal("0")
    actual_complete_pct: Decimal = Decimal("0")
    ppc: Decimal = Decimal("0")


class PPCWeeklyResponse(BaseModel):
    """Schedule-level PPC roll-up for a single week."""

    schedule_id: UUID
    week_start: date
    num_commitments: int = 0
    avg_planned_pct: Decimal = Decimal("0")
    avg_actual_pct: Decimal = Decimal("0")
    ppc: Decimal = Decimal("0")


# ── Takt / line-of-balance scheduling ──────────────────────────────────────

_TAKT_STATUS = r"^(draft|active|completed|archived)$"
_TAKT_ACTIVITY_STATUS = r"^(planned|in_progress|completed)$"


class LocationCreate(BaseModel):
    """One location in a takt schedule's location sequence."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sequence_order: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    work_area_sqm: Decimal | None = None


class LocationResponse(BaseModel):
    """Location returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    takt_schedule_id: UUID
    sequence_order: int
    name: str
    description: str = ""
    work_area_sqm: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class TaktScheduleCreate(BaseModel):
    """Create a takt schedule with its location sequence."""

    model_config = ConfigDict(str_strip_whitespace=True)

    master_schedule_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    target_cycle_days: int = Field(default=7, ge=1, le=365)
    takt_rhythm_tolerance_days: int = Field(default=1, ge=0, le=60)
    locations: list[LocationCreate] = Field(default_factory=list)


class TaktScheduleUpdate(BaseModel):
    """Patch update for a takt schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    target_cycle_days: int | None = Field(default=None, ge=1, le=365)
    takt_rhythm_tolerance_days: int | None = Field(default=None, ge=0, le=60)
    status: str | None = Field(default=None, pattern=_TAKT_STATUS)


class TaktScheduleResponse(BaseModel):
    """Takt schedule returned from the API (with nested locations)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    master_schedule_id: UUID
    name: str
    description: str = ""
    target_cycle_days: int = 7
    takt_rhythm_tolerance_days: int = 1
    location_sequence_count: int = 0
    status: str = "draft"
    created_by: UUID | None = None
    locations: list[LocationResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TaktActivityCreate(BaseModel):
    """One trade activity in a takt schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    activity_code: str = Field(default="", max_length=50)
    sequence_order: int = Field(default=1, ge=1)
    planned_cycle_duration_days: int = Field(..., ge=1, le=365)
    crew_size: int = Field(default=1, ge=1, le=10_000)
    crew_skill_codes: list[str] = Field(default_factory=list)
    buffer_days_before: int = Field(default=0, ge=0, le=365)
    sequence_predecessor_activity_id: UUID | None = None


class TaktActivityImport(BaseModel):
    """Bulk-import payload for takt activities."""

    model_config = ConfigDict(str_strip_whitespace=True)

    activities: list[TaktActivityCreate] = Field(default_factory=list)


class TaktActivityUpdate(BaseModel):
    """Patch update for a takt activity."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    activity_code: str | None = Field(default=None, max_length=50)
    sequence_order: int | None = Field(default=None, ge=1)
    planned_cycle_duration_days: int | None = Field(default=None, ge=1, le=365)
    crew_size: int | None = Field(default=None, ge=1, le=10_000)
    crew_skill_codes: list[str] | None = None
    buffer_days_before: int | None = Field(default=None, ge=0, le=365)
    actual_cycle_duration_days: Decimal | None = None
    status: str | None = Field(default=None, pattern=_TAKT_ACTIVITY_STATUS)


class TaktActivityResponse(BaseModel):
    """Takt activity returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    takt_schedule_id: UUID
    name: str
    activity_code: str = ""
    sequence_order: int = 1
    planned_cycle_duration_days: int = 1
    crew_size: int = 1
    crew_skill_codes: list[str] = Field(default_factory=list)
    buffer_days_before: int = 0
    sequence_predecessor_activity_id: UUID | None = None
    status: str = "planned"
    actual_cycle_duration_days: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class LineOfBalanceBar(BaseModel):
    """One diagonal bar on the line-of-balance chart.

    ``start_day`` / ``end_day`` are 0-based working-day indices relative to
    the takt schedule's day-zero. The chart plots the bar from
    ``(start_day, location)`` to ``(end_day, next location)`` - the diagonal
    that gives line-of-balance its name.
    """

    activity_id: UUID
    location_id: UUID
    activity_name: str
    location_name: str
    sequence_order: int
    start_day: int
    end_day: int
    crew_size: int
    is_critical: bool = False
    has_rhythm_break: bool = False


class TaktViolation(BaseModel):
    """A detected takt feasibility / rhythm issue."""

    activity_id: UUID
    location_id: UUID | None = None
    activity_name: str = ""
    location_name: str = ""
    violation_type: str  # "rhythm_break" | "overlap" | "buffer_infeasible"
    deviation_days: float = 0.0
    severity: str  # "warning" | "error"
    message: str


class LineOfBalanceResponse(BaseModel):
    """Computed line-of-balance geometry + violations + critical path."""

    takt_schedule_id: UUID
    total_makespan_days: int = 0
    bars: list[LineOfBalanceBar] = Field(default_factory=list)
    violations: list[TaktViolation] = Field(default_factory=list)
    critical_path: list[UUID] = Field(default_factory=list)
    total_locations: int = 0
    total_activities: int = 0
    average_cycle_days: float = 0.0


# ── Claims-grade schedule quality (T1.2) ─────────────────────────────────────


class FloatPathSchema(BaseModel):
    """One ranked float path. Index 0 is the Longest (driving) path."""

    index: int = 0
    activity_ids: list[str] = Field(default_factory=list)
    length_days: int = 0
    relative_float: int = 0


class QAFindingSchema(BaseModel):
    """One scheduling-quality finding (a row in the QA log)."""

    code: str
    severity: int = 0
    activity_id: str
    message: str = ""


class ActivityExplanationSchema(BaseModel):
    """Generated, numbers-faithful explain strings for one activity."""

    activity_id: str
    why_critical: str = ""
    float_explanation: str = ""


class ScheduleQualityResponse(BaseModel):
    """Response for ``POST /schedule-advanced/{schedule_id}/schedule-quality``.

    Read-only forensic view: Longest Path, ranked float paths, the scheduling
    QA log and per-activity explain strings, all derived from a single CPM pass.
    Nothing is written back to the schedule.
    """

    schedule_id: UUID
    project_finish_workday: int = 0
    num_activities: int = 0
    num_critical: int = 0
    longest_path: list[str] = Field(default_factory=list)
    longest_path_length_days: int = 0
    critical_activity_ids: list[str] = Field(default_factory=list)
    float_paths: list[FloatPathSchema] = Field(default_factory=list)
    qa_log: list[QAFindingSchema] = Field(default_factory=list)
    explanations: list[ActivityExplanationSchema] = Field(default_factory=list)


# ── Monte-Carlo schedule risk + Joint Confidence Level (T2.1) ────────────────


class ActivityRiskInputSchema(BaseModel):
    """Optional per-activity three-point duration override for a risk run.

    Activities without an entry fall back to a band derived from their stored
    duration and the run's optimistic / pessimistic percentages.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    activity_id: UUID
    low: float | None = Field(default=None, ge=0)
    mode: float | None = Field(default=None, ge=0)
    high: float | None = Field(default=None, ge=0)
    distribution: str = Field(default="pert", pattern=r"^(pert|triangular|uniform|normal|lognormal)$")


class CostRiskInputSchema(BaseModel):
    """Optional cost side of a run - enables the Joint Confidence Level.

    The three-point cost estimate is real project money, so it is Decimal-in /
    Decimal-as-string out (v3 §10); Pydantic coerces int/float/str on input.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    base_cost: Decimal = Field(..., ge=0)
    cost_low: Decimal | None = Field(default=None, ge=0)
    cost_mode: Decimal | None = Field(default=None, ge=0)
    cost_high: Decimal | None = Field(default=None, ge=0)
    cost_target: Decimal | None = Field(default=None, ge=0)
    distribution: str = Field(default="pert", pattern=r"^(pert|triangular|uniform|normal|lognormal)$")

    @field_serializer("base_cost", "cost_low", "cost_mode", "cost_high", "cost_target", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class ScheduleRiskRequest(BaseModel):
    """Body for ``POST /schedule-advanced/{schedule_id}/schedule-risk``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    iterations: int = Field(default=2000, ge=100, le=100000)
    correlation: float = Field(default=0.0, ge=0.0, le=0.95)
    seed: int | None = None
    sampling: str = Field(default="lhs", pattern=r"^(lhs|mc)$")
    target_confidence: int = Field(default=80, ge=50, le=99)
    optimistic_pct: float = Field(default=15.0, ge=0, le=100)
    pessimistic_pct: float = Field(default=25.0, ge=0, le=300)
    activity_risks: list[ActivityRiskInputSchema] = Field(default_factory=list)
    cost_inputs: CostRiskInputSchema | None = None


class CriticalityStatSchema(BaseModel):
    """How often an activity drives the schedule, and how strongly."""

    activity_id: str
    criticality_index: float = 0.0
    cruciality: float = 0.0
    duration_sensitivity: float = 0.0
    mean_duration: float = 0.0


class ScheduleDriverSchema(BaseModel):
    """A tornado entry: an activity's rank correlation to the finish."""

    activity_id: str
    rank_correlation: float = 0.0
    swing_low: float = 0.0
    swing_high: float = 0.0


class HistBinSchema(BaseModel):
    """One histogram bar over the simulated finish-day distribution."""

    bin_start: float = 0.0
    bin_end: float = 0.0
    count: int = 0


class CdfPointSchema(BaseModel):
    """One point on the cumulative S-curve (``x`` = finish work-day)."""

    x: float = 0.0
    cumulative_prob: float = 0.0


class ScatterPointSchema(BaseModel):
    """One sampled (finish, cost) draw for the JCL scatter cloud."""

    finish: float = 0.0
    cost: float = 0.0


class JointConfidenceSchema(BaseModel):
    """Joint cost / schedule confidence summary.

    ``target_cost`` (the cost target) and ``cost_mean`` (the simulated expected
    cost) are headline money figures - Decimal-as-string (v3 §10), mirroring the
    BOQ cost-risk response. ``prob_*`` are probabilities (0..1) and the scatter
    cloud carries plotted stochastic coordinates, so both stay float.
    """

    target_finish: float = 0.0
    target_cost: Decimal = Decimal("0")
    jcl: float = 0.0
    prob_on_time: float = 0.0
    prob_on_budget: float = 0.0
    cost_mean: Decimal = Decimal("0")
    cost_percentiles: dict[str, float] = Field(default_factory=dict)
    correlation: float = 0.0
    scatter: list[ScatterPointSchema] = Field(default_factory=list)

    @field_serializer("target_cost", "cost_mean", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class ScheduleRiskResponse(BaseModel):
    """Response for ``POST /schedule-advanced/{schedule_id}/schedule-risk``."""

    schedule_id: UUID
    iterations: int = 0
    deterministic_finish: float = 0.0
    mean: float = 0.0
    std_dev: float = 0.0
    cv_pct: float = 0.0
    percentiles: dict[str, float] = Field(default_factory=dict)
    contingency: float = 0.0
    contingency_pct: float = 0.0
    recommended_finish: float = 0.0
    target_confidence: int = 0
    prob_within_deterministic: float = 0.0
    correlation: float = 0.0
    seed: int = 0
    convergence_status: str = ""
    convergence_margin_pct: float = 0.0
    histogram: list[HistBinSchema] = Field(default_factory=list)
    cdf: list[CdfPointSchema] = Field(default_factory=list)
    criticality: list[CriticalityStatSchema] = Field(default_factory=list)
    drivers: list[ScheduleDriverSchema] = Field(default_factory=list)
    joint_confidence: JointConfidenceSchema | None = None


# ── Forensic delay analysis (T2.2) ───────────────────────────────────────────

_DELAY_METHOD = r"^(tia|windows|as_planned_vs_as_built|impacted_as_planned|collapsed_as_built)$"
_OOS_MODE = r"^(retained_logic|progress_override)$"
_APPORTIONMENT = r"^(none|dominant_cause|time_but_for|malmaison)$"
_RESPONSIBILITY = r"^(employer|contractor|neutral|shared)$"
_INSERT_MODE = r"^(lengthen_activity|insert_after|insert_parallel|suspend_resume)$"


class DelayAnalysisCreate(BaseModel):
    """Create a draft forensic delay analysis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    method: str = Field(default="tia", pattern=_DELAY_METHOD)
    schedule_id: UUID | None = None
    description: str = Field(default="", max_length=8000)
    as_planned_baseline_id: UUID | None = None
    as_built_snapshot_id: UUID | None = None
    oos_mode: str = Field(default="retained_logic", pattern=_OOS_MODE)
    apportionment_method: str = Field(default="malmaison", pattern=_APPORTIONMENT)
    data_date: str | None = Field(default=None, max_length=40)


class DelayAnalysisPatch(BaseModel):
    """Edit a draft analysis (status-guarded: only ``draft`` is mutable)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    method: str | None = Field(default=None, pattern=_DELAY_METHOD)
    description: str | None = Field(default=None, max_length=8000)
    as_planned_baseline_id: UUID | None = None
    as_built_snapshot_id: UUID | None = None
    oos_mode: str | None = Field(default=None, pattern=_OOS_MODE)
    apportionment_method: str | None = Field(default=None, pattern=_APPORTIONMENT)
    data_date: str | None = Field(default=None, max_length=40)


class DelayEventCreate(BaseModel):
    """Add a causative event to an analysis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1, max_length=500)
    code: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=8000)
    root_cause: str = Field(default="", max_length=8000)
    responsibility: str = Field(default="employer", pattern=_RESPONSIBILITY)
    risk_event_category: str = Field(default="", max_length=120)
    is_concurrent: bool = False
    concurrency_group: str = Field(default="", max_length=80)
    is_pacing: bool = False
    source_ref_type: str | None = Field(default=None, max_length=40)
    source_ref_id: UUID | None = None
    insert_at_activity_ref: str = Field(default="", max_length=255)
    event_start: str | None = Field(default=None, max_length=40)
    event_end: str | None = Field(default=None, max_length=40)
    start_workday: int | None = None
    end_workday: int | None = None


class DelayEventPatch(BaseModel):
    """Edit a draft event."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    code: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=8000)
    root_cause: str | None = Field(default=None, max_length=8000)
    responsibility: str | None = Field(default=None, pattern=_RESPONSIBILITY)
    risk_event_category: str | None = Field(default=None, max_length=120)
    is_concurrent: bool | None = None
    concurrency_group: str | None = Field(default=None, max_length=80)
    is_pacing: bool | None = None
    insert_at_activity_ref: str | None = Field(default=None, max_length=255)
    event_start: str | None = Field(default=None, max_length=40)
    event_end: str | None = Field(default=None, max_length=40)
    start_workday: int | None = None
    end_workday: int | None = None


class FragnetUpsert(BaseModel):
    """Define (or replace) the fragnet for an event."""

    model_config = ConfigDict(str_strip_whitespace=True)

    insert_mode: str = Field(default="lengthen_activity", pattern=_INSERT_MODE)
    insert_at_activity_ref: str = Field(..., min_length=1, max_length=255)
    added_duration_days: int = Field(default=0, ge=0, le=100000)
    fragnet_activities: list[dict] = Field(default_factory=list)
    rewires: list[dict] = Field(default_factory=list)
    applies_in_window: int | None = None


class AutoFragnetRequest(BaseModel):
    """Wizard helper: synthesise a default fragnet from a target + delay length."""

    model_config = ConfigDict(str_strip_whitespace=True)

    delay_event_id: UUID
    insert_mode: str = Field(default="lengthen_activity", pattern=_INSERT_MODE)
    insert_at_activity_ref: str = Field(..., min_length=1, max_length=255)
    added_days: int = Field(..., ge=0, le=100000)


class DelayComputeRequest(BaseModel):
    """Optional overrides for a compute run (defaults to the stored settings)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    apportionment_method: str | None = Field(default=None, pattern=_APPORTIONMENT)


class FragnetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    delay_event_id: UUID
    insert_mode: str
    insert_at_activity_ref: str
    added_duration_days: int
    fragnet_activities: list = Field(default_factory=list)
    rewires: list = Field(default_factory=list)
    applies_in_window: int | None = None


class DelayEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_id: UUID
    code: str = ""
    title: str = ""
    description: str = ""
    root_cause: str = ""
    responsibility: str = "employer"
    risk_event_category: str = ""
    is_concurrent: bool = False
    concurrency_group: str = ""
    is_pacing: bool = False
    source_ref_type: str | None = None
    source_ref_id: UUID | None = None
    insert_at_activity_ref: str = ""
    event_start: str | None = None
    event_end: str | None = None
    start_workday: int | None = None
    end_workday: int | None = None
    fragnets: list[FragnetResponse] = Field(default_factory=list)


class DelayWindowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence_order: int
    window_start: str | None = None
    window_end: str | None = None
    finish_at_open: int = 0
    finish_at_close: int = 0
    gross_slip_days: int = 0
    employer_days: int = 0
    contractor_days: int = 0
    neutral_days: int = 0
    concurrent_days: int = 0
    net_entitlement_days: int = 0
    narrative: str = ""


class DelayAnalysisListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    schedule_id: UUID | None = None
    method: str
    name: str
    status: str
    total_entitlement_days: int = 0
    window_count: int = 0
    issued_at: str | None = None


class DelayAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    schedule_id: UUID | None = None
    method: str
    name: str
    description: str = ""
    as_planned_baseline_id: UUID | None = None
    as_built_snapshot_id: UUID | None = None
    oos_mode: str = "retained_logic"
    data_date: str | None = None
    apportionment_method: str = "malmaison"
    status: str = "draft"
    window_count: int = 0
    total_entitlement_days: int = 0
    concurrent_days: int = 0
    result_json: dict = Field(default_factory=dict)
    issued_at: str | None = None
    issued_by: str | None = None
    signature_sha256: str | None = None
    eot_claim_id: UUID | None = None
    events: list[DelayEventResponse] = Field(default_factory=list)
    windows: list[DelayWindowResponse] = Field(default_factory=list)


class RaiseEotClaimResponse(BaseModel):
    """Result of raising an Extension-of-Time claim from an analysis."""

    eot_claim_id: UUID
    delay_analysis_id: UUID
    requested_days: int


# ── Last Planner board / PPC history / validation ─────────────────────────


class LpsConstraintRow(BaseModel):
    """A constraint as the board and the constraints log show it."""

    id: UUID
    task_ref: UUID
    task_name: str = ""
    constraint_type: str
    description: str = ""
    owner_user_id: UUID | None = None
    target_clear_date: date | None = None
    status: str
    cleared_at: datetime | None = None
    linked_type: str | None = None
    linked_id: UUID | None = None
    linked_label: str | None = None
    linked_status: str | None = None
    link_resolved_at: datetime | None = None


class LpsBoardTask(BaseModel):
    """One schedule activity on the look-ahead board."""

    task_ref: UUID
    name: str
    wbs_code: str = ""
    start_date: date
    end_date: date
    week_start: date
    progress_pct: Decimal
    is_ready: bool
    open_constraints: int
    committed: bool
    constraints: list[LpsConstraintRow] = Field(default_factory=list)


class LpsBoardResponse(BaseModel):
    """The look-ahead board: activities pulled from the schedule, by week."""

    look_ahead_id: UUID
    master_schedule_id: UUID
    project_id: UUID
    period_start: date
    period_end: date
    weeks: list[date]
    tasks: list[LpsBoardTask]
    ready_count: int
    blocked_count: int


class LpsPpcWeek(BaseModel):
    """PPC of one weekly work plan."""

    week_plan_id: UUID
    week_start_date: date
    status: str
    committed: int
    completed: int
    ppc_percent: Decimal | None = None


class LpsParetoRow(BaseModel):
    """One reason for variance on the Pareto chart."""

    category: str
    count: int
    percent: Decimal
    cumulative_percent: Decimal


class LpsPpcHistoryResponse(BaseModel):
    """PPC per week and the Pareto of reasons for variance."""

    master_schedule_id: UUID
    weeks: list[LpsPpcWeek]
    average_ppc: Decimal | None = None
    pareto: list[LpsParetoRow]


class LpsValidationResult(BaseModel):
    """One ``last_planner`` rule result."""

    rule_id: str
    severity: str
    passed: bool
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class LpsValidationResponse(BaseModel):
    """The ``last_planner`` rule set run over one master schedule."""

    master_schedule_id: UUID
    status: str
    errors: int
    warnings: int
    results: list[LpsValidationResult]
