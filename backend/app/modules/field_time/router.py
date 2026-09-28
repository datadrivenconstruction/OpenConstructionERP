# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Field Time API routes.

Endpoints (mounted at ``/api/v1/field-time``):

    POST   /timesheets/                          - Create a draft timesheet
    GET    /timesheets/?project_id=X             - List with filters
    GET    /timesheets/summary/?project_id=X     - Project rollup
    POST   /timesheets/suggest-cost-codes/       - Ranked cost-code suggestions
    POST   /timesheets/offline/                  - Record a day captured offline
    POST   /timesheets/offline/withdraw/         - Withdraw a day captured offline
    GET    /timesheets/working-time-regimes/     - The statutory regimes on offer
    GET    /timesheets/working-time/             - Worker-day working-time record
    GET    /timesheets/working-time.csv          - The same record as a CSV file
    GET    /timesheets/{id}/                      - Get one
    PATCH  /timesheets/{id}/                      - Update draft header
    DELETE /timesheets/{id}/                      - Delete draft
    POST   /timesheets/{id}/lines/               - Add a line to a draft
    PATCH  /timesheets/{id}/lines/{line_id}/     - Update a draft line
    DELETE /timesheets/{id}/lines/{line_id}/     - Delete a draft line
    POST   /timesheets/{id}/submit/              - Submit for approval
    POST   /timesheets/{id}/approve/             - Approve (posts hours, mints daywork)
    POST   /timesheets/{id}/reverse/             - Reverse an approved timesheet
    GET    /timesheets/{id}/validation/          - Validation report (read-only)

Every endpoint enforces project access (IDOR-safe: 404 on both missing and
forbidden) and the field_time RBAC permissions.
"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.field_time import field_time_math as ft
from app.modules.field_time import working_time as wt
from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.field_time.schemas import (
    FieldTimesheetCreate,
    FieldTimesheetLineCreate,
    FieldTimesheetLineResponse,
    FieldTimesheetLineUpdate,
    FieldTimesheetListResponse,
    FieldTimesheetResponse,
    FieldTimesheetUpdate,
    FieldTimeSummary,
    OfflineEntryResult,
    OfflineEntrySubmission,
    OfflineEntryWithdraw,
    ReverseTimesheetRequest,
    SuggestCostCodeRequest,
    SuggestCostCodeResponse,
    ValidationReportOut,
    WorkingTimeRecordOut,
    WorkingTimeRegimeOut,
    WorkingTimeStatusOut,
    WorkingTimeWorkerDayOut,
)
from app.modules.field_time.service import FieldTimeService, OfflineOpOutcome

router = APIRouter(tags=["field_time"])


def _get_service(session: SessionDep) -> FieldTimeService:
    return FieldTimeService(session)


def _line_to_response(line: FieldTimesheetLine) -> FieldTimesheetLineResponse:
    """Build a line response, deriving the labour / plant kind."""
    kind = ft.KIND_PLANT if line.equipment_id else ft.KIND_LABOUR
    return FieldTimesheetLineResponse(
        id=line.id,
        timesheet_id=line.timesheet_id,
        resource_id=line.resource_id,
        equipment_id=line.equipment_id,
        hours=line.hours if line.hours is not None else ft.to_decimal(0),
        cost_code=line.cost_code or "",
        wbs=line.wbs,
        is_daywork=bool(line.is_daywork),
        variation_id=line.variation_id,
        daywork_sheet_id=line.daywork_sheet_id,
        note=line.note,
        kind=kind,
        started_at=line.started_at,
        ended_at=line.ended_at,
        break_minutes=line.break_minutes,
        employer_kind=line.employer_kind,
        employer_subcontractor_id=line.employer_subcontractor_id,
        # A line with both clock times has its hours derived from them, so the
        # editor can say where the figure came from instead of offering to edit
        # something the server recomputes on the next write.
        hours_derived=line.started_at is not None and line.ended_at is not None,
        created_at=line.created_at,
        updated_at=line.updated_at,
    )


def _working_time_status(timesheet: FieldTimesheet) -> WorkingTimeStatusOut | None:
    """The statutory status of this day's record, or None when no regime is set.

    Never a refusal: a record made on the eighth day is late and is still the
    record. Never a deletion either - the retention window is reported and
    nothing acts on it.
    """
    spec = wt.regime_for(timesheet.working_time_regime)
    if spec is None:
        return None
    stamp = wt.timeliness(timesheet.date, timesheet.created_at, spec)
    if stamp is None:
        return None
    today = datetime.now(UTC).date()
    return WorkingTimeStatusOut(
        regime=spec.code,
        provision=spec.provision,
        deadline=stamp.deadline,
        days_taken=stamp.days_taken,
        late=stamp.late,
        retain_until=stamp.retain_until,
        within_retention=wt.within_retention(timesheet.date, spec, today),
    )


def _timesheet_to_response(timesheet: FieldTimesheet) -> FieldTimesheetResponse:
    """Build a timesheet response with its lines and the hours rollup."""
    line_dicts = [
        {
            "resource_id": str(line.resource_id) if line.resource_id else None,
            "equipment_id": str(line.equipment_id) if line.equipment_id else None,
            "hours": line.hours,
        }
        for line in timesheet.lines
    ]
    # Honour the project's rounding step (from metadata) so the header totals
    # match the summary and the payroll figures.
    config = ft.read_hours_config(getattr(timesheet, "metadata_", None))
    roll = ft.rollup(line_dicts, rounding_increment=config.rounding_increment)
    return FieldTimesheetResponse(
        working_time_regime=timesheet.working_time_regime,
        working_time=_working_time_status(timesheet),
        id=timesheet.id,
        project_id=timesheet.project_id,
        reference=timesheet.reference or "",
        date=timesheet.date,
        status=timesheet.status,
        submitted_by=timesheet.submitted_by,
        submitted_at=timesheet.submitted_at,
        approved_by=timesheet.approved_by,
        approved_at=timesheet.approved_at,
        reverses_id=timesheet.reverses_id,
        note=timesheet.note,
        metadata=getattr(timesheet, "metadata_", {}) or {},
        lines=[_line_to_response(line) for line in timesheet.lines],
        labour_hours=str(roll.labour_hours),
        plant_hours=str(roll.plant_hours),
        created_at=timesheet.created_at,
        updated_at=timesheet.updated_at,
    )


async def _authorized_timesheet(
    service: FieldTimeService,
    session: SessionDep,
    timesheet_id: uuid.UUID,
    user_id: str,
) -> FieldTimesheet:
    """Load a timesheet and assert the caller may access its project (404 else)."""
    timesheet = await service.get_timesheet(timesheet_id)
    await verify_project_access(timesheet.project_id, user_id, session)
    return timesheet


# ── Collection: static routes first (before /{id}/) ──────────────────────────


@router.get("/timesheets/summary/", response_model=FieldTimeSummary)
async def get_summary(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimeSummary:
    """Project-level rollup of field timesheets."""
    await verify_project_access(project_id, user_id, session)
    data = await service.get_summary(project_id)
    return FieldTimeSummary(
        total=data["total"],
        by_status=data["by_status"],
        labour_hours=str(data["labour_hours"]),
        plant_hours=str(data["plant_hours"]),
        overtime_hours=str(data.get("overtime_hours", "0")),
    )


@router.post("/timesheets/suggest-cost-codes/", response_model=SuggestCostCodeResponse)
async def suggest_cost_codes(
    payload: SuggestCostCodeRequest,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: FieldTimeService = Depends(_get_service),
) -> SuggestCostCodeResponse:
    """Return ranked, confidence-scored cost-code suggestions (never applied)."""
    await verify_project_access(project_id, user_id, session)
    suggestions = await service.suggest_cost_codes(project_id, payload.text, limit=payload.limit)
    return SuggestCostCodeResponse(suggestions=suggestions, applied=False)


# ── Statutory working-time record ────────────────────────────────────────────


@router.get("/timesheets/working-time-regimes/", response_model=list[WorkingTimeRegimeOut])
async def list_working_time_regimes(
    _perm: None = Depends(RequirePermission("field_time.read")),
) -> list[WorkingTimeRegimeOut]:
    """The statutory working-time regimes a project can choose to record under.

    Not project-scoped and deliberately so: this is the vocabulary, not any
    project's data. A project that chooses none of them - which is most of them,
    since this is one country's rule and the platform is used everywhere - simply
    never sends the choice back.
    """
    return [
        WorkingTimeRegimeOut(
            code=spec.code,
            label=spec.label,
            provision=spec.provision,
            record_within_days=spec.record_within_days,
            retention_years=spec.retention_years,
            summary=spec.summary,
        )
        for spec in wt.WORKING_TIME_REGIMES
    ]


async def _working_time_record(
    service: FieldTimeService,
    session: SessionDep,
    project_id: uuid.UUID,
    user_id: str,
    date_from: date,
    date_to: date,
    regime: str | None,
) -> WorkingTimeRecordOut:
    """Shared body for the two ways of asking for the record (JSON and CSV)."""
    await verify_project_access(project_id, user_id, session)
    data = await service.working_time_record(
        project_id,
        date_from=date_from,
        date_to=date_to,
        regime_code=regime,
    )
    return WorkingTimeRecordOut(
        project_id=data["project_id"],
        date_from=data["date_from"],
        date_to=data["date_to"],
        regime=data["regime"],
        provision=data["provision"],
        generated_at=data["generated_at"],
        days=[WorkingTimeWorkerDayOut(**row) for row in data["days"]],
        workers=data["workers"],
        total_hours=data["total_hours"],
        late_days=data["late_days"],
        days_missing_times=data["days_missing_times"],
        excluded_corrections=data["excluded_corrections"],
    )


@router.get("/timesheets/working-time/", response_model=WorkingTimeRecordOut)
async def get_working_time_record(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    regime: str | None = Query(None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: FieldTimeService = Depends(_get_service),
) -> WorkingTimeRecordOut:
    """Who worked on this site over this period, and when each of them started and stopped.

    One row per worker per day, which is the unit a labour inspection asks in.
    Late records are marked, not hidden and not refused, and nothing is left out
    for being outside a retention window.
    """
    return await _working_time_record(service, session, project_id, user_id, date_from, date_to, regime)


def _render_working_time_csv(days: list[WorkingTimeWorkerDayOut]) -> str:
    """Render the working-time record CSV from its plain per-day rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "date",
            "worker",
            "resource_id",
            "employer_kind",
            "employer",
            "employer_id",
            "started_at",
            "ended_at",
            "break_minutes",
            "duration_hours",
            "segments",
            "segments_without_times",
            "timesheets",
            "status",
            "recorded_at",
            "days_taken",
            "late",
            "deadline",
            "retain_until",
        ],
    )
    for row in days:
        writer.writerow(
            [
                row.date.isoformat(),
                row.worker,
                str(row.resource_id or ""),
                row.employer_kind,
                row.employer,
                str(row.employer_subcontractor_id or ""),
                row.started_at.isoformat() if row.started_at else "",
                row.ended_at.isoformat() if row.ended_at else "",
                row.break_minutes,
                row.duration_hours,
                row.segments,
                row.segments_without_times,
                " ".join(row.references),
                row.status,
                row.recorded_at.isoformat() if row.recorded_at else "",
                "" if row.days_taken is None else row.days_taken,
                "yes" if row.late else "no",
                row.deadline.isoformat() if row.deadline else "",
                row.retain_until.isoformat() if row.retain_until else "",
            ],
        )
    buf.seek(0)
    return buf.getvalue()


@router.get("/timesheets/working-time.csv")
async def export_working_time_record_csv(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    regime: str | None = Query(None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: FieldTimeService = Depends(_get_service),
) -> StreamingResponse:
    """The same record as a CSV file, which is what an inspector asks to be handed.

    Every column an auditor needs is spelled out in the row itself, including
    the worker's name beside the id: whoever opens this file has the file and
    not the database. The durations are the ones the clock times produced and
    are not put through any payroll rounding step, so a row can always be
    checked by subtracting its own columns.
    """
    record = await _working_time_record(service, session, project_id, user_id, date_from, date_to, regime)

    # Writing the file walks every worker-day of the record and is pure CPU,
    # so it runs in a worker thread; the record is already a plain pydantic model.
    csv_text = await asyncio.to_thread(_render_working_time_csv, record.days)
    filename = f"working-time-{project_id}-{record.date_from.isoformat()}-{record.date_to.isoformat()}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/timesheets/", response_model=FieldTimesheetListResponse)
async def list_timesheets(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetListResponse:
    """List one page of field timesheets for a project.

    The repository has counted the matching set since it was written and the
    count was discarded here, so the register showed a page of a project's
    week-by-week record with nothing to say how much of it was on screen.
    """
    await verify_project_access(project_id, user_id, session)
    timesheets, total = await service.list_timesheets(
        project_id,
        offset=offset,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
    )
    return FieldTimesheetListResponse(
        items=[_timesheet_to_response(t) for t in timesheets],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/timesheets/", response_model=FieldTimesheetResponse, status_code=status.HTTP_201_CREATED)
async def create_timesheet(
    payload: FieldTimesheetCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.create")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Create a new draft field timesheet."""
    await verify_project_access(payload.project_id, user_id, session)
    timesheet = await service.create_timesheet(payload, user_id)
    return _timesheet_to_response(timesheet)


# ── Offline capture and replay ───────────────────────────────────────────────


def _offline_result(outcome: OfflineOpOutcome, entry_key: str) -> OfflineEntryResult:
    """Render a service outcome as the offline API response."""
    return OfflineEntryResult(
        entry_key=entry_key,
        outcome=outcome.outcome,
        timesheet=(_timesheet_to_response(outcome.timesheet) if outcome.timesheet is not None else None),
        submitted=outcome.submitted,
        detail=outcome.detail,
    )


@router.post("/timesheets/offline/", response_model=OfflineEntryResult)
async def record_offline_entry(
    payload: OfflineEntrySubmission,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.create")),
    service: FieldTimeService = Depends(_get_service),
) -> OfflineEntryResult:
    """Record a day captured with no signal, exactly once however often it arrives.

    The body is the entry's full state and ``entry_key`` names the logical entry,
    so a replay returns the original timesheet instead of booking the hours a
    second time. Always HTTP 200: whether the day was written now or on an
    earlier delivery is in ``outcome``, not in the status code, because a device
    draining a queue has to treat both as success and stop resending.
    """
    await verify_project_access(payload.project_id, user_id, session)
    outcome = await service.record_offline_entry(payload, user_id)
    return _offline_result(outcome, payload.entry_key)


@router.post("/timesheets/offline/withdraw/", response_model=OfflineEntryResult)
async def withdraw_offline_entry(
    payload: OfflineEntryWithdraw,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.delete")),
    service: FieldTimeService = Depends(_get_service),
) -> OfflineEntryResult:
    """Withdraw a day recorded offline, by the key the device gave it.

    Remembered even when the entry is unknown here, so a withdrawal that
    overtook its own creation still stops it. Refused with HTTP 409 once the day
    has been sent on for approval - an approved timesheet is corrected by
    reversing it, never by deleting it, because deleting it would strand the
    worker-day claim its approval took.
    """
    await verify_project_access(payload.project_id, user_id, session)
    outcome = await service.withdraw_offline_entry(payload, user_id)
    return _offline_result(outcome, payload.entry_key)


# ── Item routes ──────────────────────────────────────────────────────────────


@router.get("/timesheets/{timesheet_id}/", response_model=FieldTimesheetResponse)
async def get_timesheet(
    timesheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Get a single field timesheet."""
    timesheet = await _authorized_timesheet(service, session, timesheet_id, user_id)
    return _timesheet_to_response(timesheet)


@router.patch("/timesheets/{timesheet_id}/", response_model=FieldTimesheetResponse)
async def update_timesheet(
    timesheet_id: uuid.UUID,
    payload: FieldTimesheetUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.update")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Update a draft timesheet's header fields."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    timesheet = await service.update_timesheet(timesheet_id, payload)
    return _timesheet_to_response(timesheet)


@router.delete("/timesheets/{timesheet_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_timesheet(
    timesheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.delete")),
    service: FieldTimeService = Depends(_get_service),
) -> None:
    """Delete a draft timesheet."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    await service.delete_timesheet(timesheet_id)


# ── Lines ────────────────────────────────────────────────────────────────────


@router.post("/timesheets/{timesheet_id}/lines/", response_model=FieldTimesheetResponse)
async def add_line(
    timesheet_id: uuid.UUID,
    payload: FieldTimesheetLineCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.update")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Add a line to a draft timesheet."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    timesheet = await service.add_line(timesheet_id, payload)
    return _timesheet_to_response(timesheet)


@router.patch("/timesheets/{timesheet_id}/lines/{line_id}/", response_model=FieldTimesheetResponse)
async def update_line(
    timesheet_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: FieldTimesheetLineUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.update")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Update a single line on a draft timesheet."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    timesheet = await service.update_line(timesheet_id, line_id, payload)
    return _timesheet_to_response(timesheet)


@router.delete("/timesheets/{timesheet_id}/lines/{line_id}/", response_model=FieldTimesheetResponse)
async def delete_line(
    timesheet_id: uuid.UUID,
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.update")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Delete a line from a draft timesheet."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    timesheet = await service.delete_line(timesheet_id, line_id)
    return _timesheet_to_response(timesheet)


# ── Lifecycle ────────────────────────────────────────────────────────────────


@router.post("/timesheets/{timesheet_id}/submit/", response_model=FieldTimesheetResponse)
async def submit_timesheet(
    timesheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.update")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Submit a draft timesheet for approval."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    timesheet = await service.submit_timesheet(timesheet_id, user_id)
    return _timesheet_to_response(timesheet)


@router.post("/timesheets/{timesheet_id}/approve/", response_model=FieldTimesheetResponse)
async def approve_timesheet(
    timesheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.approve")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Approve a submitted timesheet (posts hours, mints daywork sheets)."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    timesheet = await service.approve_timesheet(timesheet_id, user_id)
    return _timesheet_to_response(timesheet)


@router.post("/timesheets/{timesheet_id}/reverse/", response_model=FieldTimesheetResponse)
async def reverse_timesheet(
    timesheet_id: uuid.UUID,
    payload: ReverseTimesheetRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.approve")),
    service: FieldTimeService = Depends(_get_service),
) -> FieldTimesheetResponse:
    """Reverse an approved timesheet with a mirrored, netting timesheet."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    reversal = await service.reverse_timesheet(timesheet_id, payload, user_id)
    return _timesheet_to_response(reversal)


@router.get("/timesheets/{timesheet_id}/validation/", response_model=ValidationReportOut)
async def get_validation(
    timesheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: FieldTimeService = Depends(_get_service),
) -> ValidationReportOut:
    """Return the field-time validation report for a timesheet (read-only)."""
    await _authorized_timesheet(service, session, timesheet_id, user_id)
    data = await service.validate_timesheet(timesheet_id)
    return ValidationReportOut(**data)
