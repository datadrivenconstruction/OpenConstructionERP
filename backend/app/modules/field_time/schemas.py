# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Field Time Pydantic schemas - request / response models.

Hours are ``Decimal`` in and out but serialised to a string in JSON (the
platform-wide "money / quantity as string" convention) so a large or high
precision value never loses digits through a JavaScript ``Number``.
"""

from __future__ import annotations

# ``date`` is aliased so a Pydantic field literally named ``date`` (with a
# default) cannot shadow the type token in its own annotation, which would fail
# model construction under ``from __future__ import annotations``.
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.field_time.working_time import ALL_EMPLOYER_KINDS, ALL_WORKING_TIME_REGIMES

# Status values a timesheet can carry.
STATUS_PATTERN = r"^(draft|submitted|approved|reversed)$"

# The vocabularies of the statutory working-time record, built from the pure
# module that owns them so a new regime never has to be spelled out twice. An
# unknown code is refused at the door rather than read back as "no regime",
# which would turn a typo into a silently unrecorded legal duty.
REGIME_PATTERN = rf"^({'|'.join(ALL_WORKING_TIME_REGIMES)})$"
EMPLOYER_KIND_PATTERN = rf"^({'|'.join(ALL_EMPLOYER_KINDS)})$"


def _money_str(value: Decimal | None) -> str | None:
    """Render a Decimal as a plain, JS-safe decimal string (None passes through)."""
    if value is None:
        return None
    return format(value, "f")


# ── Line ─────────────────────────────────────────────────────────────────────


class FieldTimesheetLineCreate(BaseModel):
    """Create one labour or plant line on a timesheet.

    Exactly one of ``resource_id`` (labour) / ``equipment_id`` (plant) must be
    set - the service and a DB CHECK constraint both enforce it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    resource_id: UUID | None = None
    equipment_id: UUID | None = None
    hours: Decimal = Field(default=Decimal("0"), ge=0, le=100000, max_digits=18, decimal_places=4)
    cost_code: str = Field(default="", max_length=100)
    wbs: str | None = Field(default=None, max_length=100)
    # The bill position these hours went on, when the foreman knows which one.
    # Optional on purpose: a day spent across six positions names none of them,
    # and the estimate is better served by an honest blank than by a guess.
    boq_position_id: UUID | None = None
    is_daywork: bool = False
    variation_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    # Clock times, optional everywhere. Send both or neither: with both, the
    # server derives ``hours`` from them less the break and ignores whatever
    # ``hours`` says, so the stored duration can never contradict the times
    # beside it. ``ended_at`` is a full instant, so a night shift carries an end
    # on the following day and nothing has to be guessed.
    started_at: datetime | None = None
    ended_at: datetime | None = None
    break_minutes: int | None = Field(default=None, ge=0, le=1440)
    # Who employs this worker. Needed by a statutory working-time record because
    # a main contractor answers for the wages its subcontractors pay.
    employer_kind: str | None = Field(default=None, pattern=EMPLOYER_KIND_PATTERN)
    employer_subcontractor_id: UUID | None = None


class FieldTimesheetLineUpdate(BaseModel):
    """Partial update of a single line (draft timesheets only)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    resource_id: UUID | None = None
    equipment_id: UUID | None = None
    hours: Decimal | None = Field(default=None, ge=0, le=100000, max_digits=18, decimal_places=4)
    cost_code: str | None = Field(default=None, max_length=100)
    wbs: str | None = Field(default=None, max_length=100)
    boq_position_id: UUID | None = None
    is_daywork: bool | None = None
    variation_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    # Sending either clock time re-derives the line's hours from the pair as it
    # stands after the update; sending both as null clears the times and leaves
    # the hours as the last derived figure until somebody types a new one.
    started_at: datetime | None = None
    ended_at: datetime | None = None
    break_minutes: int | None = Field(default=None, ge=0, le=1440)
    employer_kind: str | None = Field(default=None, pattern=EMPLOYER_KIND_PATTERN)
    employer_subcontractor_id: UUID | None = None


class FieldTimesheetLineResponse(BaseModel):
    """A timesheet line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    timesheet_id: UUID
    resource_id: UUID | None = None
    equipment_id: UUID | None = None
    hours: Decimal = Decimal("0")
    cost_code: str = ""
    wbs: str | None = None
    boq_position_id: UUID | None = None
    is_daywork: bool = False
    variation_id: UUID | None = None
    daywork_sheet_id: UUID | None = None
    note: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    break_minutes: int | None = None
    employer_kind: str | None = None
    employer_subcontractor_id: UUID | None = None
    # Derived, read-only: "labour" or "plant".
    kind: str = "labour"
    # True when ``hours`` came from the clock times rather than from somebody
    # typing it. The editor greys the hours field out on those lines, because
    # editing it there would be editing a figure the server recomputes.
    hours_derived: bool = False
    created_at: datetime
    updated_at: datetime

    @field_serializer("hours", when_used="json")
    @classmethod
    def _ser_hours(cls, value: Decimal) -> str:
        return _money_str(value) or "0"


# ── Statutory working-time record ────────────────────────────────────────────


class WorkingTimeStatusOut(BaseModel):
    """When one day's record was due, whether it made it, and how long it lives."""

    regime: str
    provision: str
    deadline: date_type
    # Days between the day worked and the day the record came into existence.
    # Negative when a day was recorded before it happened.
    days_taken: int
    late: bool
    retain_until: date_type
    # True while the record still has to be kept, as of the day this was asked.
    # Nothing is deleted when it turns false; the window is reported, not acted on.
    within_retention: bool


class WorkingTimeRegimeOut(BaseModel):
    """One regime a project can choose to record its working time under."""

    code: str
    label: str
    provision: str
    record_within_days: int
    retention_years: int
    summary: str


class WorkingTimeWorkerDayOut(BaseModel):
    """One worker's working time on one day, the unit an audit asks for."""

    date: date_type
    resource_id: UUID | None = None
    # Resolved from the resources register at read time. Falls back to the id
    # when the worker is no longer in it, so a gap is visible rather than blank.
    worker: str = ""
    employer_kind: str = ""
    employer_subcontractor_id: UUID | None = None
    # The subcontractor's name, resolved the same way, or "" when the employer
    # is the main contractor's own staff or nobody said who it is.
    employer: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    break_minutes: int = 0
    # Hours as a string, the platform-wide money / quantity convention. Summed
    # from the day's bookings, each of which was derived from its own clock
    # times, and deliberately not rounded to any payroll step.
    duration_hours: str = "0"
    segments: int = 0
    # Bookings inside the day that carry hours but no clock times. Anything
    # above zero is the gap an audit would find, which is why it is a count on
    # the row and not a filter applied before the row was built.
    segments_without_times: int = 0
    references: list[str] = Field(default_factory=list)
    status: str = ""
    recorded_at: datetime | None = None
    days_taken: int | None = None
    late: bool = False
    deadline: date_type | None = None
    retain_until: date_type | None = None
    within_retention: bool = True


class WorkingTimeRecordOut(BaseModel):
    """The working-time record for a project over a period, ready for an audit.

    ``excluded_corrections`` counts the timesheets left out because they were
    reversed, or are the reversal that netted one out. They are excluded so the
    same hours are not counted twice, and counted here so the number in front of
    an auditor is never quietly narrower than it looks.
    """

    project_id: UUID
    date_from: date_type
    date_to: date_type
    regime: str | None = None
    provision: str = ""
    generated_at: datetime
    days: list[WorkingTimeWorkerDayOut] = Field(default_factory=list)
    workers: int = 0
    total_hours: str = "0"
    late_days: int = 0
    days_missing_times: int = 0
    excluded_corrections: int = 0


# ── Timesheet ────────────────────────────────────────────────────────────────


class FieldTimesheetCreate(BaseModel):
    """Create a new (draft) field timesheet, optionally with its lines."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    date: date_type
    note: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    lines: list[FieldTimesheetLineCreate] = Field(default_factory=list, max_length=1000)
    # The statutory working-time regime this day is recorded under, if any.
    # Absent means none, which is what most of the world needs and what every
    # timesheet written before this field existed says.
    working_time_regime: str | None = Field(default=None, pattern=REGIME_PATTERN)


class FieldTimesheetUpdate(BaseModel):
    """Partial update of a draft timesheet's header fields."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    date: date_type | None = None
    note: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None
    working_time_regime: str | None = Field(default=None, pattern=REGIME_PATTERN)


class FieldTimesheetResponse(BaseModel):
    """A field timesheet returned from the API, with its lines and hours rollup."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    reference: str = ""
    date: date_type
    status: str = "draft"
    submitted_by: UUID | None = None
    submitted_at: datetime | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    reverses_id: UUID | None = None
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    working_time_regime: str | None = None
    # Present only when a regime is set. Says when this day's record was due,
    # whether it made that date, and how long it has to be kept. Never a refusal
    # and never a deletion: a late record is still a record, and the product's
    # job is to say which ones are late.
    working_time: WorkingTimeStatusOut | None = None
    lines: list[FieldTimesheetLineResponse] = Field(default_factory=list)
    # Hours rollup (strings): the sum of this timesheet's line hours, split by
    # whether each line books a worker (labour) or a machine (plant). These are
    # totals of the hours as entered, not a cost figure.
    labour_hours: str = "0"
    plant_hours: str = "0"
    created_at: datetime
    updated_at: datetime


class FieldTimesheetListResponse(BaseModel):
    """One page of field timesheets plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    The project, the date window and the status filter are all applied before
    the count is taken, so a zero here means this question found nothing rather
    than the project holding nothing.

    A timesheet register grows by one row per worker per day, which makes it the
    fastest-filling list in the product. The page could hand back its ceiling
    and say nothing, and a reader adding up hours by eye would be adding up a
    slice.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[FieldTimesheetResponse]
    total: int
    offset: int
    limit: int


# ── Offline capture and replay ───────────────────────────────────────────────
#
# A day recorded on a phone with no signal is queued on the device and replayed
# when connectivity returns. The replay is at-least-once, so every op names the
# logical entry it belongs to with a client-generated ``entry_key`` and carries
# the entry's FULL state. Re-applying a full state is naturally idempotent,
# which is why no revision counter is needed to make a replay safe.

# What the server did with an offline op. A stable machine token: the client
# renders its own localized sentence from it and never parses ``detail``.
OUTCOME_CREATED = "created"  # first arrival, a new draft was written
OUTCOME_REPLAYED = "replayed"  # already applied, the original is returned
OUTCOME_UPDATED = "updated"  # a newer full state replaced the draft
OUTCOME_WITHDRAWN = "withdrawn"  # the entry is gone (or was never applied)

OUTCOME_PATTERN = r"^(created|replayed|updated|withdrawn)$"


class OfflineEntrySubmission(BaseModel):
    """One day recorded offline, as a complete replacement of that entry.

    ``entry_key`` identifies the logical entry - the foreman's record of one
    project-day - not this particular HTTP call. Every replay and every later
    edit of the same day carries the same key, which is what lets the server
    return the original row instead of writing a second one.

    The key length mirrors the field sync ledger it is stored in. A minimum of 8
    characters keeps a client from sending something that cannot be unique.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    entry_key: str = Field(..., min_length=8, max_length=128)
    project_id: UUID
    date: date_type
    note: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    lines: list[FieldTimesheetLineCreate] = Field(default_factory=list, max_length=1000)
    # When the foreman wrote the day down on the device. Advisory only: the
    # server records its own arrival time and never orders by this one.
    captured_at: datetime | None = None
    device: str | None = Field(default=None, max_length=120)
    # Send the day on for approval as part of the same op. A validation failure
    # leaves the entry as a draft rather than losing it.
    submit: bool = False


class OfflineEntryWithdraw(BaseModel):
    """Withdraw a day recorded offline, by the key the device gave it.

    ``project_id`` is required even when the entry is unknown here, because a
    withdrawal that overtakes its own creation still has to be remembered - and
    the record of it is scoped to a project.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    entry_key: str = Field(..., min_length=8, max_length=128)
    project_id: UUID


class OfflineEntryResult(BaseModel):
    """The outcome of one offline op, plus the entry as it now stands."""

    entry_key: str
    outcome: str = Field(..., pattern=OUTCOME_PATTERN)
    # The entry after the op. Absent for a withdrawal - there is nothing left.
    timesheet: FieldTimesheetResponse | None = None
    # True when the op asked to submit and the entry is now submitted. False
    # with a ``draft`` timesheet means validation held it back; the client says
    # so in its own words and points at the validation report.
    submitted: bool = False
    # English, technical, for a log or a support conversation. The client
    # renders its user-facing text from ``outcome``, never from this.
    detail: str | None = None


# ── Reverse ──────────────────────────────────────────────────────────────────


class ReverseTimesheetRequest(BaseModel):
    """Body for reversing an approved timesheet."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    note: str | None = Field(default=None, max_length=5000, description="Reason for the reversal")


# ── Validation ───────────────────────────────────────────────────────────────


class ValidationResultOut(BaseModel):
    """One validation finding for the traffic-light dashboard."""

    rule_id: str
    rule_name: str
    severity: str
    category: str
    passed: bool
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class ValidationReportOut(BaseModel):
    """Aggregated validation outcome for a timesheet."""

    status: str
    score: float | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    results: list[ValidationResultOut] = Field(default_factory=list)


# ── Cost-code suggestion (AI-augmented, human-confirmed) ─────────────────────


class SuggestCostCodeRequest(BaseModel):
    """Ask for ranked cost-code suggestions for a free-text line description."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    text: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=25)


class CostCodeSuggestionOut(BaseModel):
    """A ranked, confidence-scored cost-code suggestion the user must confirm."""

    code: str
    label: str
    confidence: float


class SuggestCostCodeResponse(BaseModel):
    """Suggestions plus an explicit reminder that nothing was applied."""

    suggestions: list[CostCodeSuggestionOut] = Field(default_factory=list)
    applied: bool = False


# ── Summary ──────────────────────────────────────────────────────────────────


class FieldTimeSummary(BaseModel):
    """Project-level rollup of field timesheets.

    Hour totals are strings (the money / quantity convention) and cover only
    live approved timesheets. ``overtime_hours`` is the portion of labour hours
    above the project's daily overtime threshold, summed per worker per day; it
    is ``"0"`` for any project that does not configure overtime.
    """

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    labour_hours: str = "0"
    plant_hours: str = "0"
    overtime_hours: str = "0"
