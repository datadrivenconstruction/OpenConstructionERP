# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Time clock API routes (included in the field time router)​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Endpoints (mounted under ``/api/v1/field-time``):

    GET    /geofences/?project_id=X                - Site fences of a project
    POST   /geofences/                             - Draw a fence
    PATCH  /geofences/{id}/                        - Edit a fence
    DELETE /geofences/{id}/                        - Remove a fence
    GET    /clock/settings/?project_id=X           - Clock settings
    PUT    /clock/settings/                        - Save clock settings
    GET    /clock/consent/?project_id=&resource_id= - A worker's consent
    POST   /clock/consent/                         - Record or withdraw consent
    POST   /clock/events/                          - Clock in or out
    POST   /clock/events/crew/                     - Clock a crew and its members
    GET    /clock/events/?project_id=X             - Clock events in a window
    POST   /clock/events/{id}/approve/             - Approve a flagged clock
    POST   /clock/events/{id}/reject/              - Reject a flagged clock
    GET    /clock/status/?project_id=X             - Who is on site now
    POST   /clock/build-timesheet/                 - Day's shifts -> draft timesheet
    GET    /clock/validation/?project_id=&date=    - Clock rules for one day
    POST   /clock/retention/purge/?project_id=X    - Erase expired positions
    GET    /clock/labour-cost/?project_id=X        - Approved labour cost (CVR)

Every endpoint checks project access (404 on missing and forbidden alike).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.field_time.clock_schemas import (
    BuildTimesheetRequest,
    ClockConsentIn,
    ClockConsentOut,
    ClockDecision,
    ClockEventCreate,
    ClockEventListResponse,
    ClockEventResponse,
    ClockLabourCost,
    ClockSettingsIn,
    ClockSettingsOut,
    ClockStatusResponse,
    CrewClockResponse,
    GeofenceCreate,
    GeofenceResponse,
    GeofenceUpdate,
    PurgeResult,
)
from app.modules.field_time.clock_service import ClockService
from app.modules.field_time.models import FieldClockEvent, FieldSiteGeofence
from app.modules.field_time.schemas import FieldTimesheetResponse, ValidationReportOut

clock_router = APIRouter()


def _service(session: SessionDep) -> ClockService:
    return ClockService(session)


def _fence_out(row: FieldSiteGeofence) -> GeofenceResponse:
    return GeofenceResponse(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        shape=row.shape,
        center_lat=None if row.center_lat is None else float(row.center_lat),
        center_lng=None if row.center_lng is None else float(row.center_lng),
        radius_m=None if row.radius_m is None else float(row.radius_m),
        polygon=[(float(p[0]), float(p[1])) for p in (row.polygon or [])],
        tolerance_m=float(row.tolerance_m or 0),
        supervisor_user_ids=[uuid.UUID(str(u)) for u in (row.supervisor_user_ids or [])],
        default_cost_code=row.default_cost_code or "",
        active=bool(row.active),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _events_out(service: ClockService, events: list[FieldClockEvent]) -> list[ClockEventResponse]:
    names = await service.repo.resource_names({e.resource_id for e in events})
    fences = {}
    for fid in {e.geofence_id for e in events if e.geofence_id}:
        fence = await service.repo.get_geofence(fid)
        if fence is not None:
            fences[fid] = fence.name
    return [
        ClockEventResponse(
            id=e.id,
            project_id=e.project_id,
            resource_id=e.resource_id,
            resource_name=names.get(e.resource_id, ""),
            kind=e.kind,
            occurred_at=e.occurred_at,
            latitude=None if e.latitude is None else float(e.latitude),
            longitude=None if e.longitude is None else float(e.longitude),
            accuracy_m=None if e.accuracy_m is None else float(e.accuracy_m),
            geofence_id=e.geofence_id,
            geofence_name=fences.get(e.geofence_id) if e.geofence_id else None,
            inside=bool(e.inside),
            distance_m=None if e.distance_m is None else float(e.distance_m),
            approval_status=e.approval_status,
            approval_reason=e.approval_reason,
            approved_by=e.approved_by,
            approved_at=e.approved_at,
            pair_event_id=e.pair_event_id,
            timesheet_id=e.timesheet_id,
            position_purged=e.position_purged_at is not None,
            note=e.note,
            created_at=e.created_at,
        )
        for e in events
    ]


# ── Geofences ────────────────────────────────────────────────────────────────


@clock_router.get("/geofences/", response_model=list[GeofenceResponse])
async def list_geofences(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: ClockService = Depends(_service),
) -> list[GeofenceResponse]:
    """Site fences of a project."""
    await verify_project_access(project_id, user_id, session)
    return [_fence_out(f) for f in await service.list_geofences(project_id)]


@clock_router.post("/geofences/", response_model=GeofenceResponse, status_code=status.HTTP_201_CREATED)
async def create_geofence(
    payload: GeofenceCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock_admin")),
    service: ClockService = Depends(_service),
) -> GeofenceResponse:
    """Draw a site fence (circle or polygon)."""
    await verify_project_access(payload.project_id, user_id, session)
    return _fence_out(await service.create_geofence(payload, user_id))


@clock_router.patch("/geofences/{geofence_id}/", response_model=GeofenceResponse)
async def update_geofence(
    geofence_id: uuid.UUID,
    payload: GeofenceUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock_admin")),
    service: ClockService = Depends(_service),
) -> GeofenceResponse:
    """Edit a site fence."""
    fence = await service.get_geofence(geofence_id)
    await verify_project_access(fence.project_id, user_id, session)
    return _fence_out(await service.update_geofence(geofence_id, payload))


@clock_router.delete("/geofences/{geofence_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_geofence(
    geofence_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock_admin")),
    service: ClockService = Depends(_service),
) -> None:
    """Remove a site fence."""
    fence = await service.get_geofence(geofence_id)
    await verify_project_access(fence.project_id, user_id, session)
    await service.delete_geofence(geofence_id)


# ── Settings + consent ───────────────────────────────────────────────────────


def _settings_out(row: object) -> ClockSettingsOut:
    return ClockSettingsOut(
        project_id=row.project_id,  # type: ignore[attr-defined]
        enabled=bool(row.enabled),  # type: ignore[attr-defined]
        retention_days=int(row.retention_days),  # type: ignore[attr-defined]
        default_break_minutes=int(row.default_break_minutes or 0),  # type: ignore[attr-defined]
        consent_text_version=row.consent_text_version or "1",  # type: ignore[attr-defined]
    )


@clock_router.get("/clock/settings/", response_model=ClockSettingsOut)
async def get_clock_settings(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: ClockService = Depends(_service),
) -> ClockSettingsOut:
    """The project's clock settings (defaults when never saved)."""
    await verify_project_access(project_id, user_id, session)
    return _settings_out(await service.get_settings(project_id))


@clock_router.put("/clock/settings/", response_model=ClockSettingsOut)
async def put_clock_settings(
    payload: ClockSettingsIn,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock_admin")),
    service: ClockService = Depends(_service),
) -> ClockSettingsOut:
    """Save the project's clock settings."""
    await verify_project_access(payload.project_id, user_id, session)
    return _settings_out(await service.put_settings(payload))


@clock_router.get("/clock/consent/", response_model=ClockConsentOut)
async def get_clock_consent(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    resource_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: ClockService = Depends(_service),
) -> ClockConsentOut:
    """A worker's consent state (not granted when never asked)."""
    await verify_project_access(project_id, user_id, session)
    row = await service.get_consent(project_id, resource_id)
    if row is None:
        return ClockConsentOut(project_id=project_id, resource_id=resource_id, granted=False)
    return ClockConsentOut(
        project_id=row.project_id,
        resource_id=row.resource_id,
        granted=bool(row.granted),
        granted_at=row.granted_at,
        withdrawn_at=row.withdrawn_at,
        text_version=row.text_version,
    )


@clock_router.post("/clock/consent/", response_model=ClockConsentOut)
async def set_clock_consent(
    payload: ClockConsentIn,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock")),
    service: ClockService = Depends(_service),
) -> ClockConsentOut:
    """Record consent, or withdraw it (which erases the worker's stored positions)."""
    await verify_project_access(payload.project_id, user_id, session)
    row = await service.set_consent(payload, user_id)
    return ClockConsentOut(
        project_id=row.project_id,
        resource_id=row.resource_id,
        granted=bool(row.granted),
        granted_at=row.granted_at,
        withdrawn_at=row.withdrawn_at,
        text_version=row.text_version,
    )


# ── Events ───────────────────────────────────────────────────────────────────


@clock_router.post("/clock/events/", response_model=ClockEventResponse, status_code=status.HTTP_201_CREATED)
async def record_clock_event(
    payload: ClockEventCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock")),
    service: ClockService = Depends(_service),
) -> ClockEventResponse:
    """Clock in or out; outside the fence is flagged for approval, never refused."""
    await verify_project_access(payload.project_id, user_id, session)
    event = await service.record_event(payload, user_id)
    return (await _events_out(service, [event]))[0]


@clock_router.post("/clock/events/crew/", response_model=CrewClockResponse, status_code=status.HTTP_201_CREATED)
async def record_crew_clock_event(
    payload: ClockEventCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock")),
    service: ClockService = Depends(_service),
) -> CrewClockResponse:
    """Clock a crew (``resource_id`` is the crew) and each of its members at one position."""
    await verify_project_access(payload.project_id, user_id, session)
    result = await service.record_crew_event(payload, user_id)
    return CrewClockResponse(events=await _events_out(service, result["events"]), skipped=result["skipped"])


@clock_router.get("/clock/events/", response_model=ClockEventListResponse)
async def list_clock_events(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    resource_id: uuid.UUID | None = Query(None),
    approval_status: str | None = Query(None, pattern="^(not_required|pending|approved|rejected)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: ClockService = Depends(_service),
) -> ClockEventListResponse:
    """Clock events in an inclusive date window, newest first."""
    await verify_project_access(project_id, user_id, session)
    events, total = await service.list_events(
        project_id,
        date_from=date_from,
        date_to=date_to,
        resource_id=resource_id,
        approval_status=approval_status,
        offset=offset,
        limit=limit,
    )
    return ClockEventListResponse(items=await _events_out(service, events), total=total)


async def _decide(
    event_id: uuid.UUID,
    payload: ClockDecision,
    session: SessionDep,
    user_id: str,
    service: ClockService,
    *,
    approve: bool,
) -> ClockEventResponse:
    event = await service.get_event(event_id)
    await verify_project_access(event.project_id, user_id, session)
    event = await service.decide(event_id, approve=approve, reason=payload.reason, user_id=user_id)
    return (await _events_out(service, [event]))[0]


@clock_router.post("/clock/events/{event_id}/approve/", response_model=ClockEventResponse)
async def approve_clock_event(
    event_id: uuid.UUID,
    payload: ClockDecision,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.approve")),
    service: ClockService = Depends(_service),
) -> ClockEventResponse:
    """Approve a clock flagged outside the fence, with a reason."""
    return await _decide(event_id, payload, session, user_id, service, approve=True)


@clock_router.post("/clock/events/{event_id}/reject/", response_model=ClockEventResponse)
async def reject_clock_event(
    event_id: uuid.UUID,
    payload: ClockDecision,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.approve")),
    service: ClockService = Depends(_service),
) -> ClockEventResponse:
    """Reject a clock flagged outside the fence, with a reason."""
    return await _decide(event_id, payload, session, user_id, service, approve=False)


@clock_router.get("/clock/status/", response_model=ClockStatusResponse)
async def clock_status(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: ClockService = Depends(_service),
) -> ClockStatusResponse:
    """Who is on site now (dashboard widget and field screen)."""
    await verify_project_access(project_id, user_id, session)
    return ClockStatusResponse(**await service.status(project_id))


@clock_router.post("/clock/build-timesheet/", response_model=FieldTimesheetResponse)
async def build_timesheet_from_clock(
    payload: BuildTimesheetRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.create")),
    service: ClockService = Depends(_service),
) -> FieldTimesheetResponse:
    """Build or refresh the day's draft timesheet from its clocked shifts."""
    from app.modules.field_time.router import _timesheet_to_response

    await verify_project_access(payload.project_id, user_id, session)
    timesheet = await service.build_timesheet(payload.project_id, payload.date, user_id)
    return _timesheet_to_response(timesheet)


@clock_router.get("/clock/validation/", response_model=ValidationReportOut)
async def clock_validation(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    day: date = Query(..., alias="date"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: ClockService = Depends(_service),
) -> ValidationReportOut:
    """Clock rules (outside unapproved, overlaps, missing clock-out) for one day."""
    await verify_project_access(project_id, user_id, session)
    return ValidationReportOut(**await service.validate_day(project_id, day))


@clock_router.post("/clock/retention/purge/", response_model=PurgeResult)
async def purge_clock_positions(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.clock_admin")),
    service: ClockService = Depends(_service),
) -> PurgeResult:
    """Erase stored positions older than the project's retention window now."""
    await verify_project_access(project_id, user_id, session)
    return PurgeResult(purged=await service.purge(project_id))


@clock_router.get("/clock/labour-cost/", response_model=ClockLabourCost)
async def clock_labour_cost(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("field_time.read")),
    service: ClockService = Depends(_service),
) -> ClockLabourCost:
    """Approved field labour hours and cost in a period, for CVR and cost control."""
    await verify_project_access(project_id, user_id, session)
    return ClockLabourCost(**await service.labour_cost(project_id, date_from, date_to))
