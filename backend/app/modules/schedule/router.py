# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule API routes.

Endpoints:
    POST   /schedules/                          - Create a new schedule
    GET    /schedules/?project_id=xxx           - List schedules for a project
    GET    /schedules/{id}                      - Get schedule detail
    PATCH  /schedules/{id}                      - Update schedule
    DELETE /schedules/{id}                      - Delete schedule
    POST   /schedules/{id}/activities           - Add activity to schedule
    GET    /schedules/{id}/activities           - List activities for schedule
    GET    /schedules/{id}/gantt                - Get Gantt chart data
    POST   /schedules/{id}/generate-from-boq   - Generate activities from BOQ
    POST   /schedules/{id}/calculate-cpm       - Calculate critical path
    GET    /schedules/{id}/risk-analysis       - PERT risk analysis
    PATCH  /activities/{id}                     - Update activity
    DELETE /activities/{id}                     - Delete activity
    POST   /activities/{id}/link-position       - Link BOQ position to activity
    PATCH  /activities/{id}/progress            - Update activity progress
    POST   /activities/{activity_id}/work-orders - Create work order
    GET    /work-orders/?schedule_id=xxx        - List work orders for schedule
    PATCH  /work-orders/{id}                    - Update work order
"""

import csv
import io
import logging
import uuid
import xml.etree.ElementTree as ET  # noqa: S405 - types + output tree building only; parsing routed through defusedxml below
from decimal import Decimal

import defusedxml.ElementTree as safe_ET
from defusedxml.common import DefusedXmlException
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

from app.core.content_disposition import attachment_disposition
from app.core.csv_safety import neutralise_formula
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule.schemas import (
    ActivityBimLinkRequest,
    ActivityCreate,
    ActivityListResponse,
    ActivityResponse,
    ActivityUpdate,
    BaselineCreate,
    BaselineResponse,
    BaselineUpdate,
    ClearActivitiesResponse,
    CPMCalculateRequest,
    CriticalPathResponse,
    EvmSummaryResponse,
    GanttData,
    GenerateFromBOQRequest,
    ImportResult,
    LaborCostByPhaseResponse,
    LinkPositionRequest,
    NextMilestone,
    ProgressUpdateCreate,
    ProgressUpdateEdit,
    ProgressUpdateRequest,
    ProgressUpdateResponse,
    RelationshipCreate,
    RelationshipResponse,
    RelationshipUpdate,
    RiskAnalysisResponse,
    ScheduleCreate,
    ScheduleDiffRequest,
    ScheduleDiffResponse,
    ScheduleListResponse,
    ScheduleResponse,
    ScheduleStatsResponse,
    ScheduleUpdate,
    SnapshotEnvelopeResponse,
    WorkCalendarResponse,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderUpdate,
)
from app.modules.schedule.service import (
    ScheduleService,
    _effective_activity_status,
    _str_to_float,
    compute_duration,
    get_work_calendar,
)

router = APIRouter(tags=["schedule"])


def _get_service(session: SessionDep) -> ScheduleService:
    return ScheduleService(session)


async def _verify_schedule_project_owner(
    session: SessionDep,
    project_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,  # noqa: ARG001 - kept for API compat; verify_project_access reads role from DB
) -> None:
    """Verify the current user owns the project. Admins bypass.

    Returns HTTP 404 on both "project missing" and "access denied" so the
    endpoint can't be turned into a UUID-existence oracle - matches the
    convention used by ``verify_project_access`` everywhere else in the
    codebase.
    """
    await verify_project_access(project_id, user_id, session)


async def _verify_schedule_owner(
    service: ScheduleService,
    session: SessionDep,
    schedule_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,  # noqa: ARG001 - kept for API compat
) -> object:
    """Load a schedule and verify the user owns its project. Admins bypass.

    Returns HTTP 404 on cross-tenant access (existence-oracle safe) so the
    schedule_id can't be enumerated by a foreign tenant. Matches the
    platform-wide convention enforced by ``verify_project_access``.
    """
    schedule = await service.get_schedule(schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return schedule


def _normalize_dependencies(deps: list | None) -> list[dict]:
    """Normalize dependencies to list[dict].

    Seeded/legacy data may store dependencies as plain UUID strings
    (e.g. ["uuid"]) instead of the expected dict format
    (e.g. [{"activity_id": "uuid", "type": "FS", "lag_days": 0}]).
    This helper ensures a consistent dict format is always returned.
    """
    if not deps:
        return []
    result: list[dict] = []
    for dep in deps:
        if isinstance(dep, str):
            result.append({"activity_id": dep, "type": "FS", "lag_days": 0})
        elif isinstance(dep, dict):
            result.append(dep)
        else:
            result.append({"activity_id": str(dep), "type": "FS", "lag_days": 0})
    return result


def _activity_to_response(activity: object) -> ActivityResponse:
    """Convert an Activity ORM model to an ActivityResponse schema."""
    return ActivityResponse(
        id=activity.id,
        schedule_id=activity.schedule_id,
        parent_id=activity.parent_id,
        name=activity.name,
        description=activity.description,
        wbs_code=activity.wbs_code,
        start_date=activity.start_date,
        end_date=activity.end_date,
        duration_days=activity.duration_days,
        progress_pct=_str_to_float(activity.progress_pct),
        status=activity.status,
        activity_type=activity.activity_type,
        dependencies=_normalize_dependencies(activity.dependencies),
        resources=activity.resources or [],
        boq_position_ids=activity.boq_position_ids or [],
        color=activity.color,
        sort_order=activity.sort_order,
        metadata_=activity.metadata_,
        created_at=activity.created_at,
        updated_at=activity.updated_at,
        # CPM fields (Phase 13)
        early_start=getattr(activity, "early_start", None),
        early_finish=getattr(activity, "early_finish", None),
        late_start=getattr(activity, "late_start", None),
        late_finish=getattr(activity, "late_finish", None),
        total_float=getattr(activity, "total_float", None),
        free_float=getattr(activity, "free_float", None),
        is_critical=getattr(activity, "is_critical", False),
        # Constraint, code, BIM fields
        constraint_type=getattr(activity, "constraint_type", None),
        constraint_date=getattr(activity, "constraint_date", None),
        activity_code=getattr(activity, "activity_code", None),
        bim_element_ids=getattr(activity, "bim_element_ids", None),
        # Per-activity work calendar (#348)
        calendar_id=getattr(activity, "calendar_id", None),
    )


def _work_order_to_response(wo: object) -> WorkOrderResponse:
    """Convert a WorkOrder ORM model to a WorkOrderResponse schema."""
    return WorkOrderResponse(
        id=wo.id,
        activity_id=wo.activity_id,
        assembly_id=wo.assembly_id,
        boq_position_id=wo.boq_position_id,
        code=wo.code,
        description=wo.description,
        assigned_to=wo.assigned_to,
        planned_start=wo.planned_start,
        planned_end=wo.planned_end,
        actual_start=wo.actual_start,
        actual_end=wo.actual_end,
        planned_cost=_str_to_float(wo.planned_cost),
        actual_cost=_str_to_float(wo.actual_cost),
        status=wo.status,
        metadata_=wo.metadata_,
        created_at=wo.created_at,
        updated_at=wo.updated_at,
    )


# ── Schedule CRUD ────────────────────────────────────────────────────────────


@router.post(
    "/schedules/",
    response_model=ScheduleResponse,
    status_code=201,
    summary="Create schedule",
    description="Create a new schedule for a project. Verifies project ownership.",
    dependencies=[Depends(RequirePermission("schedule.create"))],
)
async def create_schedule(
    data: ScheduleCreate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ScheduleResponse:
    """Create a new schedule."""
    await _verify_schedule_project_owner(session, data.project_id, _user_id, payload)
    try:
        schedule = await service.create_schedule(data)
        return ScheduleResponse.model_validate(schedule)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create schedule")
        raise HTTPException(status_code=500, detail="Failed to create schedule")


@router.get(
    "/schedules/",
    response_model=ScheduleListResponse,
    summary="List schedules",
    description="List schedules for a project. Requires project_id. Returns one page plus the total.",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_schedules(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Filter schedules by project"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ScheduleService = Depends(_get_service),
) -> ScheduleListResponse:
    """List schedules for a given project, one page at a time.

    The repository already counts the full set to build the page; this
    returns that count instead of discarding it, so a caller can tell a
    complete list from a truncated one.
    """
    await _verify_schedule_project_owner(session, project_id, _user_id, payload)
    schedules, total = await service.list_schedules_for_project(project_id, offset=offset, limit=limit)
    return ScheduleListResponse(
        items=[ScheduleResponse.model_validate(s) for s in schedules],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/schedules/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Get schedule",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_schedule(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ScheduleResponse:
    """Get a schedule by ID."""
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    schedule = await service.get_schedule(schedule_id)
    return ScheduleResponse.model_validate(schedule)


@router.patch(
    "/schedules/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Update schedule",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_schedule(
    schedule_id: uuid.UUID,
    data: ScheduleUpdate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ScheduleResponse:
    """Update schedule metadata (name, description, status, dates)."""
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    schedule = await service.update_schedule(schedule_id, data)
    return ScheduleResponse.model_validate(schedule)


@router.delete(
    "/schedules/{schedule_id}",
    status_code=204,
    summary="Delete schedule",
    dependencies=[Depends(RequirePermission("schedule.delete"))],
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> None:
    """Delete a schedule and all its activities and work orders."""
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    await service.delete_schedule(schedule_id)


# ── Activity CRUD ────────────────────────────────────────────────────────────


@router.post(
    "/schedules/{schedule_id}/activities/",
    response_model=ActivityResponse,
    status_code=201,
    summary="Create activity",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_activity(
    schedule_id: uuid.UUID,
    data: ActivityCreate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Add a new activity to a schedule.

    The schedule_id in the URL takes precedence over the body field.
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    # Override body schedule_id with URL path parameter
    data.schedule_id = schedule_id
    activity = await service.create_activity(data)
    return _activity_to_response(activity)


@router.get(
    "/schedules/{schedule_id}/activities/",
    response_model=ActivityListResponse,
    summary="List activities",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_activities(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=5000),
    service: ScheduleService = Depends(_get_service),
) -> ActivityListResponse:
    """List activities for a schedule, ordered by sort_order, one page at a time.

    Verifies the caller owns the parent project (admins bypass) so a user
    cannot enumerate activities of a schedule they do not have access to.

    Returns the schedule's full activity count alongside the page. A Gantt
    or 4D viewer that draws ``items`` without checking ``total`` renders a
    programme that is missing work and looks finished.
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    activities, total = await service.list_activities_for_schedule(schedule_id, offset=offset, limit=limit)
    return ActivityListResponse(
        items=[_activity_to_response(a) for a in activities],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete(
    "/schedules/{schedule_id}/activities/",
    response_model=ClearActivitiesResponse,
    summary="Clear all activities (reset schedule)",
    dependencies=[Depends(RequirePermission("schedule.delete"))],
)
async def clear_activities(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ClearActivitiesResponse:
    """Delete every activity (and its work orders) of a schedule in one call.

    Backs the schedule "Reset" action so the client no longer fires an N+1
    serial DELETE per activity. Verifies the caller owns the parent project
    (admins bypass).
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    deleted = await service.clear_activities(schedule_id)
    return ClearActivitiesResponse(schedule_id=schedule_id, deleted=deleted)


@router.get(
    "/schedules/{schedule_id}/gantt/",
    response_model=GanttData,
    summary="Get Gantt chart data",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_gantt_data(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> GanttData:
    """Get structured Gantt chart data for a schedule.

    Verifies the caller owns the parent project (admins bypass).
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    return await service.get_gantt_data(schedule_id)


# ── CPM & BOQ Generation ───────────────────────────────────────────────────


@router.post(
    "/schedules/{schedule_id}/generate-from-boq/",
    response_model=list[ActivityResponse],
    status_code=201,
    summary="Generate activities from BOQ",
    description="Auto-generate schedule activities from a BOQ. Creates one activity per "
    "section with cost-proportional durations and sequential FS dependencies.",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def generate_from_boq(
    schedule_id: uuid.UUID,
    body: GenerateFromBOQRequest,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> list[ActivityResponse]:
    """Generate schedule activities from a BOQ.

    Creates one activity per BOQ section with cost-proportional durations
    and sequential finish-to-start dependencies. Verifies the caller owns
    the parent project (admins bypass) before mutating the schedule.
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    try:
        await service.generate_from_boq(schedule_id, body.boq_id, body.total_project_days)
        # Re-fetch activities to avoid greenlet/lazy-loading issues
        activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)
        return [_activity_to_response(a) for a in activities]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate_from_boq failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate schedule from BOQ. Check server logs for details.",
        ) from exc


@router.post(
    "/schedules/{schedule_id}/calculate-cpm/",
    response_model=CriticalPathResponse,
    summary="Calculate critical path (CPM)",
    description="Run CPM forward/backward pass on a schedule. Returns early/late start/finish, "
    "total float, and critical path. Updates activity colors (red=critical, blue=non-critical).",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def calculate_cpm(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> CriticalPathResponse:
    """Calculate the critical path (CPM forward/backward pass).

    Returns early/late start/finish, total float, and critical path for all
    activities. Updates activity colors: red for critical, blue for non-critical.
    Verifies the caller owns the parent project (admins bypass) before
    mutating activity CPM fields.
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    return await service.calculate_critical_path(schedule_id)


@router.get(
    "/schedules/{schedule_id}/risk-analysis/",
    response_model=RiskAnalysisResponse,
    summary="Get PERT risk analysis",
    description="Compute PERT-based risk analysis with P50, P80, P95 duration estimates. "
    "Derives optimistic/pessimistic durations for each activity and project-level "
    "probability estimates for schedule completion.",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_risk_analysis(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> RiskAnalysisResponse:
    """Get PERT-based risk analysis with P50, P80, P95 duration estimates.

    Computes optimistic/pessimistic durations for each activity and derives
    project-level probability estimates for schedule completion. Verifies the
    caller owns the parent project (admins bypass) - risk analysis re-runs
    CPM, which mutates activity fields.
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    return await service.get_risk_analysis(schedule_id)


@router.get(
    "/schedules/{schedule_id}/evm-summary/",
    response_model=EvmSummaryResponse,
    summary="Get earned-value (EVM) summary",
    description="Scalar earned-value metrics for a schedule at a data date: "
    "PV/EV/AC, BAC, schedule/cost variance, SPI/CPI and the CPI-based forecast "
    "(EAC/ETC/VAC). Reuses the same time-phased computation as the 4D dashboard.",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_evm_summary(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
    as_of_date: str | None = Query(
        default=None,
        description="Data date (ISO YYYY-MM-DD). Defaults to today when omitted.",
    ),
) -> EvmSummaryResponse:
    """Return scalar earned-value metrics for a schedule.

    Read-only rollup over the schedule's cost-loaded activities. Verifies the
    caller owns the parent project (admins bypass) and returns HTTP 404 on a
    missing/foreign schedule, matching the platform existence-oracle-safe
    convention. ``spi`` / ``cpi`` and the EAC/ETC/VAC forecast are ``null``
    when the schedule has no cost data or a denominator is zero.

    Every money field is rounded to the minor unit of the project's currency,
    which travels back on ``currency``. ``evm_math`` is deliberately free of
    app imports and cannot look a currency up, so the quantum is resolved here
    and handed to it. This is the same rounding the 4D dashboard applies to the
    same schedule: the two surfaces have to agree, and before the quantum was
    passed they did not.
    """
    from datetime import date as _date

    from app.core.money import money_quantum
    from app.modules.schedule.evm_math import EvmCostRow, compute_evm_summary
    from app.modules.schedule.service_4d import resolve_schedule_currency

    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)

    # Parse the data date defensively (mirror the 4D router contract).
    if as_of_date:
        try:
            target = _date.fromisoformat(as_of_date[:10])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"as_of_date must be ISO YYYY-MM-DD, got {as_of_date!r}",
            ) from exc
    else:
        target = _date.today()

    activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)
    rows = [
        EvmCostRow(
            start_date=a.start_date,
            end_date=a.end_date,
            cost_planned=a.cost_planned,
            cost_actual=a.cost_actual,
            progress_pct=a.progress_pct,
        )
        for a in activities
    ]
    currency = await resolve_schedule_currency(session, schedule_id)
    summary = compute_evm_summary(rows, target, quantum=money_quantum(currency))
    data = summary.to_json()
    return EvmSummaryResponse(
        schedule_id=schedule_id,
        as_of_date=target.isoformat(),
        currency=currency,
        planned_value=Decimal(str(data["planned_value"])),
        earned_value=Decimal(str(data["earned_value"])),
        actual_cost=Decimal(str(data["actual_cost"])),
        budget_at_completion=Decimal(str(data["budget_at_completion"])),
        schedule_variance=Decimal(str(data["schedule_variance"])),
        cost_variance=Decimal(str(data["cost_variance"])),
        estimate_at_completion=(
            Decimal(str(data["estimate_at_completion"])) if data["estimate_at_completion"] is not None else None
        ),
        estimate_to_complete=(
            Decimal(str(data["estimate_to_complete"])) if data["estimate_to_complete"] is not None else None
        ),
        variance_at_completion=(
            Decimal(str(data["variance_at_completion"])) if data["variance_at_completion"] is not None else None
        ),
        spi=data["spi"],
        cpi=data["cpi"],
        has_cost_data=data["has_cost_data"],
    )


@router.patch(
    "/activities/{activity_id}",
    response_model=ActivityResponse,
    summary="Update activity",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_activity(
    activity_id: uuid.UUID,
    data: ActivityUpdate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Update a schedule activity. Recalculates duration if dates changed."""
    existing = await service.get_activity(activity_id)
    await _verify_schedule_owner(service, session, existing.schedule_id, _user_id, payload)
    activity = await service.update_activity(activity_id, data)
    return _activity_to_response(activity)


@router.delete(
    "/activities/{activity_id}",
    status_code=204,
    summary="Delete activity",
    dependencies=[Depends(RequirePermission("schedule.delete"))],
)
async def delete_activity(
    activity_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> None:
    """Delete an activity and its work orders."""
    existing = await service.get_activity(activity_id)
    await _verify_schedule_owner(service, session, existing.schedule_id, _user_id, payload)
    await service.delete_activity(activity_id)


@router.post(
    "/activities/{activity_id}/link-position/",
    response_model=ActivityResponse,
    summary="Link BOQ position to activity",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def link_boq_position(
    activity_id: uuid.UUID,
    body: LinkPositionRequest,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Link a BOQ position to an activity."""
    existing = await service.get_activity(activity_id)
    await _verify_schedule_owner(service, session, existing.schedule_id, _user_id, payload)
    activity = await service.link_boq_position(activity_id, body.boq_position_id)
    return _activity_to_response(activity)


@router.patch(
    "/activities/{activity_id}/progress/",
    response_model=ActivityResponse,
    summary="Update activity progress",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_activity_progress(
    activity_id: uuid.UUID,
    body: ProgressUpdateRequest,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Update activity progress percentage. Auto-adjusts status."""
    existing = await service.get_activity(activity_id)
    await _verify_schedule_owner(service, session, existing.schedule_id, _user_id, payload)
    activity = await service.update_progress(activity_id, body.progress_pct)
    return _activity_to_response(activity)


@router.patch(
    "/activities/{activity_id}/bim-links/",
    response_model=ActivityResponse,
    summary="Replace BIM element links on an activity",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_activity_bim_links(
    activity_id: uuid.UUID,
    body: ActivityBimLinkRequest,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Replace the full ``bim_element_ids`` array on an activity (4D linking).

    The caller supplies the complete desired list; partial add/remove should
    be handled client-side by reading the current value first.
    """
    activity = await service.get_activity(activity_id)
    await _verify_schedule_owner(service, session, activity.schedule_id, _user_id, payload)
    updated = await service.update_bim_links(activity_id, body.bim_element_ids)
    return _activity_to_response(updated)


@router.get(
    "/activities/by-bim-element/",
    response_model=list[ActivityResponse],
    summary="List activities linked to a BIM element",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_activities_by_bim_element(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    element_id: str = Query(..., description="BIM element UUID to look up"),
    project_id: uuid.UUID = Query(..., description="Project scope for the search"),
    service: ScheduleService = Depends(_get_service),
) -> list[ActivityResponse]:
    """Reverse query: return every activity in ``project_id`` whose
    ``bim_element_ids`` array contains ``element_id``.
    """
    await _verify_schedule_project_owner(session, project_id, _user_id, payload)
    activities = await service.get_activities_for_bim_element(element_id, project_id)
    return [_activity_to_response(act) for act in activities]


# ── Work Order CRUD ──────────────────────────────────────────────────────────


@router.post(
    "/activities/{activity_id}/work-orders/",
    response_model=WorkOrderResponse,
    status_code=201,
    summary="Create work order",
    dependencies=[Depends(RequirePermission("schedule.work_orders.manage"))],
)
async def create_work_order(
    activity_id: uuid.UUID,
    data: WorkOrderCreate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> WorkOrderResponse:
    """Create a new work order for an activity.

    The activity_id in the URL takes precedence over the body field.
    """
    existing = await service.get_activity(activity_id)
    await _verify_schedule_owner(service, session, existing.schedule_id, _user_id, payload)
    # Override body activity_id with URL path parameter
    data.activity_id = activity_id
    work_order = await service.create_work_order(data)
    return _work_order_to_response(work_order)


@router.get(
    "/work-orders/",
    response_model=list[WorkOrderResponse],
    summary="List work orders",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_work_orders(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    schedule_id: uuid.UUID = Query(..., description="Filter work orders by schedule"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ScheduleService = Depends(_get_service),
) -> list[WorkOrderResponse]:
    """List all work orders for a schedule.

    Verifies the caller owns the parent project (admins bypass).
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    work_orders, _ = await service.list_work_orders_for_schedule(schedule_id, offset=offset, limit=limit)
    return [_work_order_to_response(wo) for wo in work_orders]


@router.patch(
    "/work-orders/{work_order_id}",
    response_model=WorkOrderResponse,
    summary="Update work order",
    dependencies=[Depends(RequirePermission("schedule.work_orders.manage"))],
)
async def update_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderUpdate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> WorkOrderResponse:
    """Update a work order."""
    existing_wo = await service.get_work_order(work_order_id)
    existing_act = await service.get_activity(existing_wo.activity_id)
    await _verify_schedule_owner(service, session, existing_act.schedule_id, _user_id, payload)
    work_order = await service.update_work_order(work_order_id, data)
    return _work_order_to_response(work_order)


# ── Schedule Relationships (Phase 13) ───────────────────────────────────────


@router.post(
    "/schedules/{schedule_id}/relationships/",
    response_model=RelationshipResponse,
    status_code=201,
    summary="Create CPM relationship",
    description="Create a dependency relationship between two activities. "
    "Validates against self-references and circular dependencies.",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_relationship(
    schedule_id: uuid.UUID,
    data: RelationshipCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ScheduleService = Depends(_get_service),
) -> RelationshipResponse:
    """Create a CPM dependency relationship between two activities.

    Validates:
    - predecessor and successor are not the same activity
    - no circular dependency would be created
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    from sqlalchemy import select

    from app.modules.schedule.models import ScheduleRelationship

    # ── Reject self-referencing dependency ────────────────────────────────
    if data.predecessor_id == data.successor_id:
        raise HTTPException(
            status_code=400,
            detail="An activity cannot depend on itself.",
        )

    # ── Reject circular dependencies ─────────────────────────────────────
    # Build adjacency from existing relationships, then check if adding the
    # new edge (predecessor -> successor) would create a cycle by testing
    # reachability from successor back to predecessor.
    stmt = select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)
    result = await session.execute(stmt)
    existing_rels = list(result.scalars().all())

    # adjacency: predecessor_id -> set of successor_ids
    adjacency: dict[uuid.UUID, set[uuid.UUID]] = {}
    for r in existing_rels:
        adjacency.setdefault(r.predecessor_id, set()).add(r.successor_id)

    # Temporarily add the proposed edge
    adjacency.setdefault(data.predecessor_id, set()).add(data.successor_id)

    # BFS from successor to see if we can reach predecessor (cycle)
    visited: set[uuid.UUID] = set()
    queue: list[uuid.UUID] = [data.successor_id]
    while queue:
        current = queue.pop(0)
        if current == data.predecessor_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Adding this dependency would create a circular reference. Check the dependency chain for cycles."
                ),
            )
        if current in visited:
            continue
        visited.add(current)
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                queue.append(neighbor)

    # Idempotent upsert against the unique (predecessor, successor) constraint:
    # if the edge already exists, update its type/lag instead of raising an
    # IntegrityError. ScheduleRelationship is the canonical store, so a repeat
    # create is a "set this edge" operation.
    dup = next(
        (r for r in existing_rels if r.predecessor_id == data.predecessor_id and r.successor_id == data.successor_id),
        None,
    )
    if dup is not None:
        dup.relationship_type = data.relationship_type
        dup.lag_days = data.lag_days
        await session.flush()
        rel = dup
    else:
        rel = ScheduleRelationship(
            schedule_id=schedule_id,
            predecessor_id=data.predecessor_id,
            successor_id=data.successor_id,
            relationship_type=data.relationship_type,
            lag_days=data.lag_days,
        )
        session.add(rel)
        await session.flush()

    # Build the detached response model now, while ``rel`` holds exactly what
    # was created, so the payload describes the new relationship and not the
    # successor's derived-JSON rebuild below - and so serialising it never
    # lazy-loads, which raises MissingGreenlet.
    response = RelationshipResponse.model_validate(rel)

    # Rebuild the successor activity's derived ``dependencies`` JSON mirror from
    # the canonical rows so the convenience field never drifts from the table.
    derived = await service._derive_dependencies_json(data.successor_id)
    await service.activity_repo.update_fields(data.successor_id, dependencies=derived)

    return response


@router.get(
    "/schedules/{schedule_id}/relationships/",
    response_model=list[RelationshipResponse],
    summary="List CPM relationships",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_relationships(
    schedule_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ScheduleService = Depends(_get_service),
    limit: int = Query(
        default=200,
        ge=1,
        le=500,
        description=(
            "Maximum number of relationships to return. Default 200 covers "
            "the vast majority of project schedules; the hard cap of 500 "
            "protects the request from blowing memory + serialisation cost "
            "on pathological imports (some MPP files carry 5k+ dependency "
            "rows). For full CPM analysis use ``/cpm`` which intentionally "
            "fetches every relationship server-side without sending them "
            "over the wire."
        ),
    ),
) -> list[RelationshipResponse]:
    """List CPM relationships for a schedule (capped, paginated by limit).

    Previously fetched every relationship without bound - a schedule with
    a few thousand dependency rows (typical from large MS Project / P6
    imports) would dump 10+ MB JSON on a UI grid that only renders the
    first hundred. Capped at ``limit`` (default 200, max 500) and
    deterministically ordered by ``created_at`` so pagination is stable.
    Callers that need the full set should iterate via the dedicated
    ``/cpm`` endpoint which keeps the data server-side.
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    from sqlalchemy import select

    from app.modules.schedule.models import ScheduleRelationship

    stmt = (
        select(ScheduleRelationship)
        .where(ScheduleRelationship.schedule_id == schedule_id)
        .order_by(ScheduleRelationship.created_at.asc(), ScheduleRelationship.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rels = list(result.scalars().all())
    return [RelationshipResponse.model_validate(r) for r in rels]


@router.delete(
    "/relationships/{relationship_id}",
    status_code=204,
    summary="Delete relationship",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def delete_relationship(
    relationship_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleService = Depends(_get_service),
) -> None:
    """Delete a schedule relationship.

    Guard against cross-project sabotage: non-admin users must own the
    parent project or the request is rejected with 404 (404 instead of
    403 so we don't leak existence of unknown relationship ids).

    Deletes the canonical edge, then rebuilds the successor activity's derived
    ``dependencies`` JSON mirror so the removed edge truly disappears from CPM
    (the historical bug left a lingering JSON copy that kept blocking).
    """
    from sqlalchemy import delete, select

    from app.dependencies import verify_project_access
    from app.modules.schedule.models import Schedule, ScheduleRelationship

    rel = await session.get(ScheduleRelationship, relationship_id)
    if rel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")

    sched = (await session.execute(select(Schedule).where(Schedule.id == rel.schedule_id))).scalar_one_or_none()
    if sched is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")

    await verify_project_access(sched.project_id, user_id, session)

    successor_id = rel.successor_id
    stmt = delete(ScheduleRelationship).where(ScheduleRelationship.id == relationship_id)
    await session.execute(stmt)
    await session.flush()

    derived = await service._derive_dependencies_json(successor_id)
    await service.activity_repo.update_fields(successor_id, dependencies=derived)


@router.patch(
    "/relationships/{relationship_id}",
    response_model=RelationshipResponse,
    summary="Update CPM relationship",
    description="Update the type and/or lag of an existing dependency edge. The "
    "edge endpoints are immutable, so the self-reference and cycle guards that "
    "run on create cannot be violated by a type/lag change.",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_relationship(
    relationship_id: uuid.UUID,
    data: RelationshipUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ScheduleService = Depends(_get_service),
) -> RelationshipResponse:
    """Update the type / lag of an existing dependency relationship.

    Loads the edge, verifies the caller owns the parent project (admins
    bypass), applies the partial change via the canonical relationship store,
    then rebuilds the successor activity's derived ``dependencies`` JSON mirror
    so the convenience field never drifts from the table. The predecessor /
    successor endpoints are immutable, so no self-reference or cycle can be
    introduced here - re-pointing an edge is a delete + create, which re-runs
    the create-route guards.
    """
    from app.modules.schedule.models import ScheduleRelationship

    rel = await session.get(ScheduleRelationship, relationship_id)
    if rel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")

    # Existence-oracle-safe ownership check (404 on cross-tenant access).
    await _verify_schedule_owner(service, session, rel.schedule_id, _user_id, payload)

    successor_id = rel.successor_id
    merged_type = data.relationship_type or rel.relationship_type
    merged_lag = data.lag_days if data.lag_days is not None else rel.lag_days

    await service.relationship_repo.update_edge(
        relationship_id,
        relationship_type=merged_type,
        lag_days=merged_lag,
    )
    # Reflect the persisted values on the in-memory row, then snapshot the
    # response before the mirror rebuild so the payload describes the
    # relationship itself rather than the successor's derived JSON, and never
    # lazy-loads while serialising (MissingGreenlet).
    rel.relationship_type = merged_type
    rel.lag_days = merged_lag
    response = RelationshipResponse.model_validate(rel)

    # Keep the successor activity's derived dependency JSON in lock-step with
    # the canonical row so CPM / the Gantt read the new type/lag.
    derived = await service._derive_dependencies_json(successor_id)
    await service.activity_repo.update_fields(successor_id, dependencies=derived)

    return response


@router.post(
    "/schedules/{schedule_id}/reschedule/",
    response_model=list[ActivityResponse],
    summary="Reschedule (CPM-driven dates)",
    description="Recompute activity dates from the dependency network. Activities "
    "with a predecessor are moved to their CPM early-date positions; root "
    "activities keep their manually set start. Returns the updated activities.",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def reschedule_schedule(
    schedule_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ScheduleService = Depends(_get_service),
) -> list[ActivityResponse]:
    """Reschedule a schedule's activities from its dependency network.

    Verifies the caller owns the parent project (admins bypass), runs the CPM
    engine over the canonical relationship edges, projects the early-date
    offsets onto calendar dates, and persists the moved bars plus the
    critical-path flag / float columns. Root activities keep their manual
    start. Called by the dependency editor after every edge change so the bars
    move as soon as a link is added, retyped, relagged or removed.
    """
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    activities = await service.reschedule(schedule_id)
    return [_activity_to_response(a) for a in activities]


# ── CPM Calculation (Phase 13 - uses core/cpm.py engine) ────────────────────


@router.post(
    "/schedule/cpm/calculate/",
    response_model=CriticalPathResponse,
    summary="Run full CPM calculation",
    description="Full CPM calculation using the core engine. Reads activities and "
    "ScheduleRelationship records, runs forward/backward pass, computes floats, "
    "identifies the critical path, and persists results on each activity.",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def calculate_cpm_full(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    schedule_id: uuid.UUID = Query(..., description="Schedule to run CPM on"),
    body: CPMCalculateRequest | None = None,
    session: SessionDep = None,
    service: ScheduleService = Depends(_get_service),
) -> CriticalPathResponse:
    """Run full CPM calculation using the core engine and store results.

    Reads activities and explicit ScheduleRelationship records (plus inline
    dependency JSON) to build the network.  Runs forward/backward pass,
    computes floats, identifies the critical path, persists CPM results on
    each activity, and returns the full analysis. Verifies the caller owns
    the parent project (admins bypass) before mutating activity CPM fields.
    """
    from sqlalchemy import select

    from app.core.cpm import calculate_cpm
    from app.modules.schedule.models import ScheduleRelationship
    from app.modules.schedule.schemas import CPMActivityResult

    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    schedule = await service.get_schedule(schedule_id)
    activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)

    if not activities:
        raise HTTPException(status_code=404, detail="Schedule has no activities")

    # Build activity dicts for CPM engine
    act_dicts = []
    for act in activities:
        act_dicts.append(
            {
                "id": str(act.id),
                "duration": act.duration_days or 0,
                "name": act.name,
            }
        )

    # Build the edge set from the canonical ScheduleRelationship store ONLY.
    # The table is the single source of truth; Activity.dependencies JSON is a
    # derived mirror. Reading the table alone means a relationship the user
    # deleted truly disappears from CPM instead of being re-introduced by a
    # lingering JSON copy.
    rel_dicts: list[dict] = []

    rel_stmt = select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)
    rel_result = await session.execute(rel_stmt)
    canonical_rows = list(rel_result.scalars().all())
    for r in canonical_rows:
        rel_dicts.append(
            {
                "predecessor_id": str(r.predecessor_id),
                "successor_id": str(r.successor_id),
                "type": r.relationship_type,
                "lag": r.lag_days,
            }
        )

    # Legacy fallback: only when no canonical rows exist for this schedule do
    # we read the inline JSON, so un-reconciled historical schedules still
    # compute. Once the table holds any edge it is the sole authority.
    if not canonical_rows:
        for act in activities:
            deps = act.dependencies or []
            for dep in deps:
                if isinstance(dep, dict):
                    pred_id = dep.get("activity_id", "")
                    rel_dicts.append(
                        {
                            "predecessor_id": str(pred_id),
                            "successor_id": str(act.id),
                            "type": dep.get("type", "FS"),
                            "lag": dep.get("lag_days", 0),
                        }
                    )
                elif isinstance(dep, str):
                    rel_dicts.append(
                        {
                            "predecessor_id": dep,
                            "successor_id": str(act.id),
                            "type": "FS",
                            "lag": 0,
                        }
                    )

    # Deduplicate relationships by (pred, succ)
    seen: set[tuple[str, str]] = set()
    unique_rels: list[dict] = []
    for r in rel_dicts:
        key = (r["predecessor_id"], r["successor_id"])
        if key not in seen:
            seen.add(key)
            unique_rels.append(r)

    # Run CPM engine
    calendar_dict = body.calendar if body else None
    cpm_results = await calculate_cpm(
        act_dicts,
        unique_rels,
        calendar=calendar_dict,
        project_start_date=schedule.start_date,
    )

    # Build lookup from CPM results
    cpm_map = {r["id"]: r for r in cpm_results}

    # Persist CPM results on each activity and build response
    all_cpm: list[CPMActivityResult] = []
    critical_path: list[CPMActivityResult] = []
    project_duration = 0

    for act in activities:
        aid = str(act.id)
        cpm = cpm_map.get(aid)
        if cpm is None:
            continue

        es = cpm["early_start"]
        ef = cpm["early_finish"]
        ls = cpm["late_start"]
        lf = cpm["late_finish"]
        tf = cpm["total_float"]
        ff = cpm["free_float"]
        is_crit = cpm["is_critical"]

        # Persist to DB
        await service.activity_repo.update_fields(
            act.id,
            early_start=str(es),
            early_finish=str(ef),
            late_start=str(ls),
            late_finish=str(lf),
            total_float=tf,
            free_float=ff,
            is_critical=is_crit,
            color="#dc2626" if is_crit else "#0071e3",
        )

        project_duration = max(project_duration, ef)

        result = CPMActivityResult(
            activity_id=act.id,
            name=act.name,
            duration_days=act.duration_days or 0,
            early_start=es,
            early_finish=ef,
            late_start=ls,
            late_finish=lf,
            total_float=tf,
            is_critical=is_crit,
        )
        all_cpm.append(result)
        if is_crit:
            critical_path.append(result)

    return CriticalPathResponse(
        schedule_id=schedule_id,
        project_duration_days=project_duration,
        critical_path=critical_path,
        all_activities=all_cpm,
    )


# ── Schedule Baselines ─────────────────────────────────────────────────────


@router.post(
    "/baselines/",
    response_model=BaselineResponse,
    status_code=201,
    summary="Create baseline",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_baseline(
    data: BaselineCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> BaselineResponse:
    """Create a schedule baseline snapshot."""
    await verify_project_access(data.project_id, _user_id, session)
    from app.modules.schedule.models import ScheduleBaseline

    baseline = ScheduleBaseline(
        schedule_id=data.schedule_id,
        project_id=data.project_id,
        name=data.name,
        baseline_date=data.baseline_date,
        snapshot_data=data.snapshot_data,
        is_active=data.is_active,
        created_by=data.created_by,
        metadata_=data.metadata,
    )
    session.add(baseline)
    await session.flush()
    return BaselineResponse.model_validate(baseline)


@router.get(
    "/baselines/",
    response_model=list[BaselineResponse],
    summary="List baselines",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_baselines(
    project_id: uuid.UUID = Query(..., description="Filter baselines by project"),
    session: SessionDep = None,
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[BaselineResponse]:
    """List all baselines for a project."""
    await verify_project_access(project_id, _user_id, session)
    from sqlalchemy import select

    from app.modules.schedule.models import ScheduleBaseline

    stmt = (
        select(ScheduleBaseline)
        .where(ScheduleBaseline.project_id == project_id)
        .order_by(ScheduleBaseline.created_at.desc())
    )
    result = await session.execute(stmt)
    baselines = list(result.scalars().all())
    return [BaselineResponse.model_validate(b) for b in baselines]


@router.get(
    "/baselines/{baseline_id}",
    response_model=BaselineResponse,
    summary="Get baseline",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_baseline(
    baseline_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> BaselineResponse:
    """Get a single baseline by ID."""
    from app.modules.schedule.models import ScheduleBaseline

    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail=translate("errors.baseline_not_found", locale=get_locale()))
    await verify_project_access(baseline.project_id, _user_id, session)
    return BaselineResponse.model_validate(baseline)


@router.patch(
    "/baselines/{baseline_id}",
    response_model=BaselineResponse,
    summary="Toggle baseline active flag",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_baseline(
    baseline_id: uuid.UUID,
    data: BaselineUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> BaselineResponse:
    """Toggle a baseline's ``is_active`` flag.

    Baselines are snapshot-in-time records and must stay immutable
    (``name``, ``baseline_date``, ``snapshot_data``, ``metadata``) so that
    EVM / planned-vs-actual comparisons and contractual forensics remain
    trustworthy months later. Only the active-flag workflow toggle is
    exposed here. Any other field in the request body is rejected by the
    schema (``BaselineUpdate`` deliberately omits them).
    """
    from sqlalchemy import update

    from app.modules.schedule.models import ScheduleBaseline

    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail=translate("errors.baseline_not_found", locale=get_locale()))
    await verify_project_access(baseline.project_id, _user_id, session)

    updates = data.model_dump(exclude_unset=True)
    if updates:
        stmt = update(ScheduleBaseline).where(ScheduleBaseline.id == baseline_id).values(**updates)
        await session.execute(stmt)
        await session.flush()
        session.expire_all()
        baseline = await session.get(ScheduleBaseline, baseline_id)
    return BaselineResponse.model_validate(baseline)


@router.delete(
    "/baselines/{baseline_id}",
    status_code=204,
    summary="Delete baseline (admin only)",
    dependencies=[Depends(RequirePermission("schedule.baselines.delete"))],
)
async def delete_baseline(
    baseline_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    """Delete a baseline. Admin-only: see ``schedule.baselines.delete``."""
    from app.modules.schedule.models import ScheduleBaseline

    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail=translate("errors.baseline_not_found", locale=get_locale()))
    await verify_project_access(baseline.project_id, _user_id, session)
    await session.delete(baseline)
    await session.flush()


# ── Progress Updates ───────────────────────────────────────────────────────


@router.post(
    "/progress-updates/",
    response_model=ProgressUpdateResponse,
    status_code=201,
    summary="Create progress update",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_progress_update(
    data: ProgressUpdateCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> ProgressUpdateResponse:
    """Create a progress update record."""
    await verify_project_access(data.project_id, _user_id, session)
    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    record = ProgressUpdateModel(
        project_id=data.project_id,
        activity_id=data.activity_id,
        update_date=data.update_date,
        progress_pct=data.progress_pct,
        actual_start=data.actual_start,
        actual_finish=data.actual_finish,
        remaining_duration=data.remaining_duration,
        notes=data.notes,
        status=data.status,
        submitted_by=data.submitted_by,
        approved_by=data.approved_by,
        metadata_=data.metadata,
    )
    session.add(record)
    await session.flush()
    return ProgressUpdateResponse.model_validate(record)


@router.get(
    "/progress-updates/",
    response_model=list[ProgressUpdateResponse],
    summary="List progress updates",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_progress_updates(
    project_id: uuid.UUID = Query(..., description="Filter by project"),
    activity_id: uuid.UUID | None = Query(default=None, description="Filter by activity"),
    session: SessionDep = None,
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[ProgressUpdateResponse]:
    """List progress updates for a project, optionally filtered by activity."""
    await verify_project_access(project_id, _user_id, session)
    from sqlalchemy import select

    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    stmt = select(ProgressUpdateModel).where(ProgressUpdateModel.project_id == project_id)
    if activity_id is not None:
        stmt = stmt.where(ProgressUpdateModel.activity_id == activity_id)
    stmt = stmt.order_by(ProgressUpdateModel.created_at.desc())

    result = await session.execute(stmt)
    records = list(result.scalars().all())
    return [ProgressUpdateResponse.model_validate(r) for r in records]


@router.get(
    "/progress-updates/{update_id}",
    response_model=ProgressUpdateResponse,
    summary="Get progress update",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_progress_update(
    update_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> ProgressUpdateResponse:
    """Get a single progress update by ID."""
    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    record = await session.get(ProgressUpdateModel, update_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Progress update not found")
    await verify_project_access(record.project_id, _user_id, session)
    return ProgressUpdateResponse.model_validate(record)


@router.patch(
    "/progress-updates/{update_id}",
    response_model=ProgressUpdateResponse,
    summary="Update progress update",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_progress_update(
    update_id: uuid.UUID,
    data: ProgressUpdateEdit,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> ProgressUpdateResponse:
    """Update a progress update record."""
    from sqlalchemy import update

    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    record = await session.get(ProgressUpdateModel, update_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Progress update not found")
    await verify_project_access(record.project_id, _user_id, session)

    updates = data.model_dump(exclude_unset=True)
    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")
    if updates:
        stmt = update(ProgressUpdateModel).where(ProgressUpdateModel.id == update_id).values(**updates)
        await session.execute(stmt)
        await session.flush()
        session.expire_all()
        record = await session.get(ProgressUpdateModel, update_id)
    return ProgressUpdateResponse.model_validate(record)


@router.delete(
    "/progress-updates/{update_id}",
    status_code=204,
    summary="Delete progress update",
    dependencies=[Depends(RequirePermission("schedule.delete"))],
)
async def delete_progress_update(
    update_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    """Delete a progress update record."""
    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    record = await session.get(ProgressUpdateModel, update_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Progress update not found")
    await verify_project_access(record.project_id, _user_id, session)
    await session.delete(record)
    await session.flush()


# ── Import / Export ───────────────────────────────────────────────────────


def _parse_xer_tables(content: str) -> dict[str, list[dict[str, str]]]:
    """Parse the XER tab-delimited exchange format into table dictionaries.

    XER format uses:
      %T <TABLE_NAME>     - start of a table
      %F <col1> <col2>    - field (column) names
      %R <val1> <val2>    - row values

    Returns a dict mapping table name to a list of row dicts.
    """
    tables: dict[str, list[dict[str, str]]] = {}
    current_table: str | None = None
    current_fields: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.rstrip("\r\n")
        if not line or not line.startswith("%"):
            continue
        parts = line.split("\t")
        directive = parts[0] if parts else ""

        if directive == "%T" and len(parts) >= 2:
            current_table = parts[1].strip()
            current_fields = []
            if current_table not in tables:
                tables[current_table] = []
        elif directive == "%F" and current_table is not None:
            current_fields = [p.strip() for p in parts[1:]]
        elif directive == "%R" and current_table is not None and current_fields:
            values = parts[1:]
            row: dict[str, str] = {}
            for i, field in enumerate(current_fields):
                row[field] = values[i].strip() if i < len(values) else ""
            tables[current_table].append(row)

    return tables


@router.post(
    "/schedule/import/xer/",
    response_model=ImportResult,
    status_code=201,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def import_xer(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    schedule_id: uuid.UUID = Query(..., description="Target schedule to import into"),
    file: UploadFile = File(...),
    session: SessionDep = None,
    service: ScheduleService = Depends(_get_service),
) -> ImportResult:
    """Import an XER schedule export into a schedule.

    Parses TASK, TASKPRED, and CALENDAR tables from the XER format and creates
    activities and relationships in the target schedule.
    """
    from app.modules.schedule.models import Activity, ScheduleRelationship
    from app.modules.schedule.xer_encoding import decode_xer

    # Verify schedule exists
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)

    # Read and decode file. A P6 export carries no declaration of its code
    # page, and the pair this used to be, utf-8 then latin-1, could not fail:
    # latin-1 accepts every byte, so an Arabic, Russian, Greek or Hebrew
    # export imported silently with every name turned to mojibake.
    raw = await file.read()
    content, code_page = decode_xer(raw)

    tables = _parse_xer_tables(content)
    warnings: list[str] = []
    if code_page not in ("utf-8", "utf-8-sig"):
        # Said out loud rather than logged. The person importing is the only
        # one who knows which machine exported the file, and a guess that
        # reads Arabic out of an English programme is worth their attention
        # while they can still re-export it.
        warnings.append(
            f"File carries no encoding declaration; read as {code_page}. "
            "Check the activity names if this is not the code page of the machine that exported it."
        )

    # ── Parse TASK table ──────────────────────────────────────────────────
    tasks = tables.get("TASK", [])
    if not tasks:
        raise HTTPException(status_code=400, detail="No TASK table found in XER file")

    # Map XER task_id -> our Activity UUID for relationship linking
    xer_id_to_uuid: dict[str, uuid.UUID] = {}
    activities_imported = 0

    # Get current max activity code for auto-gen
    max_seq = await service.activity_repo.get_max_activity_code_seq(schedule_id)

    for task_idx, task_row in enumerate(tasks):
        xer_task_id = task_row.get("task_id", "")
        task_code = task_row.get("task_code", "")
        task_name = task_row.get("task_name", "") or task_code or f"Task-{xer_task_id}"

        # Try multiple date field names (P6 versions vary)
        start_date = (
            task_row.get("target_start_date")
            or task_row.get("act_start_date")
            or task_row.get("early_start_date")
            or ""
        )
        end_date = (
            task_row.get("target_end_date") or task_row.get("act_end_date") or task_row.get("early_end_date") or ""
        )

        # Normalize dates: XER may use "YYYY-MM-DD HH:MM" or "YYYY-MM-DD"
        start_date = start_date[:10] if start_date else ""
        end_date = end_date[:10] if end_date else ""

        if not start_date or not end_date:
            warnings.append(f"Task {task_code}: missing start/end date, using defaults")
            start_date = start_date or "2026-01-01"
            end_date = end_date or "2026-01-15"

        # Duration
        try:
            duration_days = int(float(task_row.get("target_drtn_hr_cnt", "0")) / 8)
        except (ValueError, TypeError):
            duration_days = 0
        if duration_days == 0:
            duration_days = max(1, compute_duration(start_date, end_date))

        # Task type
        task_type_xer = task_row.get("task_type", "TT_Task")
        if "Mile" in task_type_xer or "WBS" in task_type_xer:
            activity_type = "milestone"
        elif "Summary" in task_type_xer or "LOE" in task_type_xer:
            activity_type = "summary"
        else:
            activity_type = "task"

        # Progress
        try:
            pct = float(task_row.get("phys_complete_pct", "0"))
        except (ValueError, TypeError):
            pct = 0.0

        # Constraint
        constraint_type = task_row.get("cstr_type", None)
        constraint_date = task_row.get("cstr_date", None)
        if constraint_date:
            constraint_date = constraint_date[:10]

        max_seq += 1
        activity_code = task_code if task_code else f"ACT-{max_seq:03d}"

        activity = Activity(
            schedule_id=schedule_id,
            parent_id=None,
            name=task_name[:255],
            description=task_row.get("task_name", ""),
            wbs_code=task_row.get("wbs_id", ""),
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            progress_pct=str(pct),
            status="completed" if pct >= 100 else ("in_progress" if pct > 0 else "not_started"),
            activity_type=activity_type,
            dependencies=[],
            resources=[],
            boq_position_ids=[],
            color="#dc2626" if activity_type == "milestone" else "#0071e3",
            sort_order=task_idx + 1,
            activity_code=activity_code,
            constraint_type=constraint_type,
            constraint_date=constraint_date,
            metadata_={"source": "xer_import", "xer_task_id": xer_task_id},
        )
        session.add(activity)
        await session.flush()
        xer_id_to_uuid[xer_task_id] = activity.id
        activities_imported += 1

    # ── Parse TASKPRED table (relationships) ──────────────────────────────
    preds = tables.get("TASKPRED", [])
    relationships_imported = 0

    # Map XER pred_type to our types
    pred_type_map = {
        "PR_FS": "FS",
        "PR_FF": "FF",
        "PR_SS": "SS",
        "PR_SF": "SF",
    }

    for pred_row in preds:
        pred_task_id = pred_row.get("pred_task_id", "")
        succ_task_id = pred_row.get("task_id", "")
        pred_uuid = xer_id_to_uuid.get(pred_task_id)
        succ_uuid = xer_id_to_uuid.get(succ_task_id)

        if pred_uuid is None or succ_uuid is None:
            warnings.append(f"Relationship {pred_task_id}->{succ_task_id}: predecessor or successor not found, skipped")
            continue

        if pred_uuid == succ_uuid:
            continue

        rel_type_xer = pred_row.get("pred_type", "PR_FS")
        rel_type = pred_type_map.get(rel_type_xer, "FS")

        try:
            lag = int(float(pred_row.get("lag_hr_cnt", "0")) / 8)
        except (ValueError, TypeError):
            lag = 0

        rel = ScheduleRelationship(
            schedule_id=schedule_id,
            predecessor_id=pred_uuid,
            successor_id=succ_uuid,
            relationship_type=rel_type,
            lag_days=lag,
        )
        session.add(rel)
        relationships_imported += 1

    await session.flush()

    # ── Parse CALENDAR table ──────────────────────────────────────────────
    calendars = tables.get("CALENDAR", [])
    calendars_imported = len(calendars)
    if calendars:
        # Store calendar data in schedule metadata for reference
        schedule = await service.get_schedule(schedule_id)
        meta = dict(schedule.metadata_ or {})
        meta["xer_calendars"] = calendars[:10]  # Limit stored data
        await service.schedule_repo.update_fields(schedule_id, metadata_=meta)

    return ImportResult(
        activities_imported=activities_imported,
        relationships_imported=relationships_imported,
        calendars_imported=calendars_imported,
        warnings=warnings,
    )


def _parse_msp_duration_to_days(duration_str: str) -> int:
    """Parse MS Project XML duration string (e.g. 'PT48H0M0S', 'P5D') to days.

    MSP durations use ISO 8601 duration format:
    - PT48H0M0S = 48 hours = 6 days (at 8h/day)
    - P5DT0H0M0S = 5 days
    - PT0H0M0S = 0 (milestone)
    """
    if not duration_str:
        return 0

    total_hours = 0.0
    total_days = 0

    # Extract days (P...D)
    d_part = duration_str.split("T")[0] if "T" in duration_str else duration_str
    if "D" in d_part:
        try:
            d_val = d_part.replace("P", "").replace("D", "")
            total_days = int(d_val)
        except (ValueError, TypeError):
            pass

    # Extract hours from time part (T...H)
    if "T" in duration_str:
        t_part = duration_str.split("T")[1]
        if "H" in t_part:
            try:
                h_val = t_part.split("H")[0]
                total_hours = float(h_val)
            except (ValueError, TypeError):
                pass

    # Convert hours to days (assuming 8h workday)
    total_days += int(total_hours / 8)
    return max(total_days, 0)


@router.post(
    "/schedule/import/msp-xml/",
    response_model=ImportResult,
    status_code=201,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def import_msp_xml(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    schedule_id: uuid.UUID = Query(..., description="Target schedule to import into"),
    file: UploadFile = File(...),
    session: SessionDep = None,
    service: ScheduleService = Depends(_get_service),
) -> ImportResult:
    """Import an MS Project XML file into a schedule.

    Supports both MSP 2016 and MSP 2021 formats. Extracts Tasks and Links
    (predecessor relationships) and maps them to Activity + ScheduleRelationship.
    """
    from app.modules.schedule.models import Activity, ScheduleRelationship

    # Verify schedule exists
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)

    raw = await file.read()

    try:
        # Parsed from bytes on purpose. MSPDI, unlike XER, states its own
        # encoding in the XML declaration, and ElementTree honours that only
        # when it is handed bytes; a str has already been decoded and the
        # declaration can no longer be acted on, so it is silently ignored.
        # This used to decode utf-8 then latin-1 first, which cannot fail and
        # therefore turned a windows-1256 file into mojibake that parsed
        # perfectly well.
        root = safe_ET.fromstring(raw)
    except DefusedXmlException as e:
        # Hostile payload (XXE / billion-laughs / external DTD): defusedxml
        # raises EntitiesForbidden/DTDForbidden/ExternalReferenceForbidden,
        # which are NOT ET.ParseError - reject cleanly instead of 500.
        raise HTTPException(
            status_code=400,
            detail="XML rejected for security reasons",
        ) from e
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {e}") from e

    warnings: list[str] = []

    # Detect namespace (MSP 2003/2016 vs 2021+)
    ns = ""
    root_tag = root.tag
    if "}" in root_tag:
        ns = root_tag.split("}")[0] + "}"

    def find(parent: ET.Element, tag: str) -> ET.Element | None:
        """Find child element with or without namespace."""
        result = parent.find(f"{ns}{tag}")
        if result is None:
            result = parent.find(tag)
        return result

    def findall(parent: ET.Element, tag: str) -> list[ET.Element]:
        """Find all child elements with or without namespace."""
        result = parent.findall(f"{ns}{tag}")
        if not result:
            result = parent.findall(tag)
        return result

    def findtext(parent: ET.Element, tag: str, default: str = "") -> str:
        """Get text of child element with or without namespace."""
        el = find(parent, tag)
        return (el.text or default) if el is not None else default

    # ── Parse Tasks ───────────────────────────────────────────────────────
    tasks_elem = find(root, "Tasks")
    if tasks_elem is None:
        raise HTTPException(status_code=400, detail="No Tasks element found in MSP XML")

    task_elements = findall(tasks_elem, "Task")
    if not task_elements:
        raise HTTPException(status_code=400, detail="No Task elements found in MSP XML")

    # Map MSP UID -> our UUID
    msp_uid_to_uuid: dict[str, uuid.UUID] = {}
    activities_imported = 0
    max_seq = await service.activity_repo.get_max_activity_code_seq(schedule_id)

    for task_idx, task_el in enumerate(task_elements):
        uid = findtext(task_el, "UID", "")
        name = findtext(task_el, "Name", "")
        if not name:
            continue

        # Skip the root summary task (UID=0 in MSP)
        if uid == "0":
            continue

        start = findtext(task_el, "Start", "")
        finish = findtext(task_el, "Finish", "")
        duration_str = findtext(task_el, "Duration", "")
        pct_str = findtext(task_el, "PercentComplete", "0")
        outline_level = findtext(task_el, "OutlineLevel", "1")
        summary_flag = findtext(task_el, "Summary", "0")
        milestone_flag = findtext(task_el, "Milestone", "0")
        wbs = findtext(task_el, "WBS", "")

        # Normalize dates: MSP XML uses "2026-05-01T08:00:00"
        start_date = start[:10] if start else ""
        end_date = finish[:10] if finish else ""

        if not start_date or not end_date:
            warnings.append(f"Task UID={uid} '{name}': missing dates, using defaults")
            start_date = start_date or "2026-01-01"
            end_date = end_date or "2026-01-15"

        duration_days = _parse_msp_duration_to_days(duration_str)
        if duration_days == 0 and start_date and end_date:
            duration_days = max(0, compute_duration(start_date, end_date))

        try:
            pct = float(pct_str)
        except (ValueError, TypeError):
            pct = 0.0

        # Determine activity type
        if milestone_flag == "1" or duration_days == 0:
            activity_type = "milestone"
        elif summary_flag == "1":
            activity_type = "summary"
        else:
            activity_type = "task"

        # Constraint
        constraint_type_str = findtext(task_el, "ConstraintType", "")
        constraint_date_str = findtext(task_el, "ConstraintDate", "")
        constraint_map = {
            "0": "as_soon_as_possible",
            "1": "must_start_on",
            "2": "must_finish_on",
            "3": "start_no_earlier",
            "4": "start_no_later",
            "5": "finish_no_earlier",
            "6": "finish_no_later",
            "7": "as_late_as_possible",
        }
        constraint_type = constraint_map.get(constraint_type_str)
        constraint_date = constraint_date_str[:10] if constraint_date_str else None

        max_seq += 1
        activity_code = f"ACT-{max_seq:03d}"

        activity = Activity(
            schedule_id=schedule_id,
            parent_id=None,
            name=name[:255],
            description=name,
            wbs_code=wbs,
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            progress_pct=str(pct),
            status="completed" if pct >= 100 else ("in_progress" if pct > 0 else "not_started"),
            activity_type=activity_type,
            dependencies=[],
            resources=[],
            boq_position_ids=[],
            color="#dc2626" if activity_type == "milestone" else "#0071e3",
            sort_order=task_idx + 1,
            activity_code=activity_code,
            constraint_type=constraint_type,
            constraint_date=constraint_date,
            metadata_={
                "source": "msp_xml_import",
                "msp_uid": uid,
                "outline_level": outline_level,
            },
        )
        session.add(activity)
        await session.flush()
        msp_uid_to_uuid[uid] = activity.id
        activities_imported += 1

    # ── Parse Links (predecessors) ────────────────────────────────────────
    relationships_imported = 0

    # MSP link types: 0=FF, 1=FS, 2=SF, 3=SS
    msp_link_type_map = {
        "0": "FF",
        "1": "FS",
        "2": "SF",
        "3": "SS",
    }

    for task_el in task_elements:
        uid = findtext(task_el, "UID", "")
        succ_uuid = msp_uid_to_uuid.get(uid)
        if succ_uuid is None:
            continue

        # Links can be nested under Task
        pred_links = findall(task_el, "PredecessorLink")
        for link_el in pred_links:
            pred_uid = findtext(link_el, "PredecessorUID", "")
            pred_uuid = msp_uid_to_uuid.get(pred_uid)
            if pred_uuid is None:
                warnings.append(f"Link: predecessor UID={pred_uid} not found for task UID={uid}")
                continue

            if pred_uuid == succ_uuid:
                continue

            link_type = findtext(link_el, "Type", "1")
            rel_type = msp_link_type_map.get(link_type, "FS")

            lag_str = findtext(link_el, "LinkLag", "0")
            try:
                # MSP stores lag in tenths of minutes; convert to days
                lag_tenths = int(lag_str)
                lag_days = lag_tenths // (10 * 60 * 8) if lag_tenths != 0 else 0
            except (ValueError, TypeError):
                lag_days = 0

            rel = ScheduleRelationship(
                schedule_id=schedule_id,
                predecessor_id=pred_uuid,
                successor_id=succ_uuid,
                relationship_type=rel_type,
                lag_days=lag_days,
            )
            session.add(rel)
            relationships_imported += 1

    await session.flush()

    return ImportResult(
        activities_imported=activities_imported,
        relationships_imported=relationships_imported,
        calendars_imported=0,
        warnings=warnings,
    )


@router.get(
    "/schedule/export/csv/",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def export_schedule_csv(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    schedule_id: uuid.UUID = Query(..., description="Schedule to export"),
    service: ScheduleService = Depends(_get_service),
    session: SessionDep = None,
) -> StreamingResponse:
    """Export schedule activities as a CSV file.

    Columns: Activity Code, Name, WBS, Start, End, Duration, Progress, Float,
    Critical, Predecessors. Verifies the caller owns the parent project
    (admins bypass).
    """
    from sqlalchemy import select

    from app.modules.schedule.models import ScheduleRelationship

    # Verify schedule exists & caller owns the parent project
    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    schedule = await service.get_schedule(schedule_id)

    # Fetch activities
    activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)

    # Fetch relationships for predecessor lookup
    rel_stmt = select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)
    rel_result = await session.execute(rel_stmt)
    relationships = list(rel_result.scalars().all())

    # Build successor -> list of predecessor info
    # Also map activity UUID -> activity_code for display
    act_code_map: dict[str, str] = {}
    for act in activities:
        act_code_map[str(act.id)] = act.activity_code or act.wbs_code or str(act.id)[:8]

    predecessor_map: dict[str, list[str]] = {}
    for rel in relationships:
        succ_id = str(rel.successor_id)
        pred_code = act_code_map.get(str(rel.predecessor_id), str(rel.predecessor_id)[:8])
        lag_str = f"+{rel.lag_days}d" if rel.lag_days > 0 else ""
        pred_label = f"{pred_code}{rel.relationship_type}{lag_str}"
        predecessor_map.setdefault(succ_id, []).append(pred_label)

    # Also include inline dependencies
    for act in activities:
        act_id = str(act.id)
        inline_deps = act.dependencies or []
        for dep in inline_deps:
            if isinstance(dep, dict):
                pred_id = str(dep.get("activity_id", ""))
                dep_type = dep.get("type", "FS")
                lag = dep.get("lag_days", 0)
                pred_code = act_code_map.get(pred_id, pred_id[:8])
                lag_str = f"+{lag}d" if lag and lag > 0 else ""
                pred_label = f"{pred_code}{dep_type}{lag_str}"
                predecessor_map.setdefault(act_id, []).append(pred_label)

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Activity Code",
            "Name",
            "WBS",
            "Start",
            "End",
            "Duration (days)",
            "Progress (%)",
            "Total Float",
            "Critical",
            "Predecessors",
        ]
    )

    for act in activities:
        act_id = str(act.id)
        preds = predecessor_map.get(act_id, [])
        # Deduplicate predecessors
        preds = list(dict.fromkeys(preds))

        # Neutralise every string-bearing cell so a value a user controls
        # (activity name/code/WBS, or a derived predecessor label built from
        # them) that starts with =, +, -, @, tab or CR cannot be interpreted as
        # a formula when the CSV is opened in Excel / Sheets / LibreOffice
        # (CSV/formula injection - OWASP). Numeric cells pass through unchanged.
        writer.writerow(
            [
                neutralise_formula(act.activity_code or ""),
                neutralise_formula(act.name),
                neutralise_formula(act.wbs_code),
                neutralise_formula(act.start_date),
                neutralise_formula(act.end_date),
                act.duration_days,
                _str_to_float(act.progress_pct),
                act.total_float if act.total_float is not None else "",
                "Yes" if act.is_critical else "No",
                neutralise_formula("; ".join(preds)),
            ]
        )

    csv_content = output.getvalue()
    output.close()

    schedule_name = schedule.name.replace(" ", "_")[:40]
    filename = f"schedule_{schedule_name}.csv"

    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": attachment_disposition(filename)},
    )


@router.get(
    "/schedule/export/msp-xml/",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def export_schedule_msp_xml(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    schedule_id: uuid.UUID = Query(..., description="Schedule to export"),
    service: ScheduleService = Depends(_get_service),
    session: SessionDep = None,
) -> StreamingResponse:
    """Export a schedule as a Microsoft Project XML (MSPDI) file.

    Round-trips with ``import_msp_xml``: tasks become ``<Task>`` rows (UID,
    dates, 8h-day duration, percent complete, milestone/summary flags,
    constraints) and both the relationship table and inline dependencies
    become ``<PredecessorLink>`` entries. Verifies the caller owns the parent
    project (admins bypass).
    """
    from sqlalchemy import select

    from app.modules.schedule.models import ScheduleRelationship
    from app.modules.schedule.mspdi_export import (
        MspdiActivity,
        MspdiPredecessor,
        MspdiProject,
        build_mspdi_xml,
    )

    await _verify_schedule_owner(service, session, schedule_id, _user_id, payload)
    schedule = await service.get_schedule(schedule_id)
    activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)

    # Stable 1..N UID per activity, preserving the listed order.
    uid_by_act: dict[str, int] = {}
    mspdi_acts: list[MspdiActivity] = []
    for idx, act in enumerate(activities, start=1):
        uid_by_act[str(act.id)] = idx
        mspdi_acts.append(
            MspdiActivity(
                uid=idx,
                name=act.name or "",
                start_date=act.start_date or "",
                end_date=act.end_date or "",
                duration_days=act.duration_days or 0,
                progress_pct=_str_to_float(act.progress_pct),
                activity_type=act.activity_type or "task",
                wbs_code=act.wbs_code or "",
                constraint_type=act.constraint_type,
                constraint_date=act.constraint_date,
            )
        )

    # Predecessor links: relationship rows first, then inline dependencies.
    # Dedupe by (predecessor UID, relationship type) so a link recorded both
    # ways is only emitted once.
    preds_by_uid: dict[int, list[MspdiPredecessor]] = {}
    seen: set[tuple[int, int, str]] = set()

    def _add_link(succ_uid: int, pred_uid: int, rel_type: str, lag_days: int) -> None:
        key = (succ_uid, pred_uid, rel_type)
        if pred_uid == succ_uid or key in seen:
            return
        seen.add(key)
        preds_by_uid.setdefault(succ_uid, []).append(
            MspdiPredecessor(
                predecessor_uid=pred_uid,
                relationship_type=rel_type,
                lag_days=lag_days,
            )
        )

    rel_stmt = select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)
    rel_result = await session.execute(rel_stmt)
    for rel in rel_result.scalars().all():
        succ = uid_by_act.get(str(rel.successor_id))
        pred = uid_by_act.get(str(rel.predecessor_id))
        if succ is None or pred is None:
            continue
        _add_link(succ, pred, rel.relationship_type or "FS", rel.lag_days or 0)

    for act in activities:
        succ = uid_by_act.get(str(act.id))
        if succ is None:
            continue
        for dep in act.dependencies or []:
            if not isinstance(dep, dict):
                continue
            pred = uid_by_act.get(str(dep.get("activity_id", "")))
            if pred is None:
                continue
            try:
                lag = int(dep.get("lag_days", 0) or 0)
            except (TypeError, ValueError):
                lag = 0
            _add_link(succ, pred, str(dep.get("type", "FS")), lag)

    xml_str = build_mspdi_xml(
        MspdiProject(
            name=schedule.name or "Schedule",
            activities=mspdi_acts,
            predecessors_by_uid=preds_by_uid,
        )
    )

    schedule_name = schedule.name.replace(" ", "_")[:40]
    filename = f"schedule_{schedule_name}.xml"
    return StreamingResponse(
        io.BytesIO(xml_str.encode("utf-8")),
        media_type="application/xml",
        headers={"Content-Disposition": attachment_disposition(filename)},
    )


# ── Schedule Stats & Critical Path ──────────────────────────────────────────


@router.get(
    "/stats/",
    response_model=ScheduleStatsResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def schedule_stats(
    project_id: uuid.UUID = Query(..., description="Project to compute stats for"),
    session: SessionDep = None,  # type: ignore[assignment]
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ScheduleStatsResponse:
    """Return aggregate schedule statistics across all schedules in a project.

    Computes total activities, critical count, delayed, on_track, progress_pct, etc.
    """
    await verify_project_access(project_id, _user_id, session)
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.modules.projects.repository import ProjectRepository
    from app.modules.schedule.models import Activity, Schedule

    # Get all schedules for the project
    sched_stmt = select(Schedule.id).where(Schedule.project_id == project_id)
    sched_result = await session.execute(sched_stmt)
    schedule_ids = [row[0] for row in sched_result.all()]

    if not schedule_ids:
        return ScheduleStatsResponse()

    # Get all activities across those schedules
    act_stmt = select(Activity).where(Activity.schedule_id.in_(schedule_ids))
    act_result = await session.execute(act_stmt)
    activities = list(act_result.scalars().all())

    total = len(activities)
    if total == 0:
        return ScheduleStatsResponse()

    # Resolve the project region + today so "delayed" is derived the same way
    # as the Gantt summary (overdue + unfinished), keeping the rollup honest.
    project = await ProjectRepository(session).get_by_id(project_id)
    project_region = project.region if project else None
    today = datetime.now(UTC).date()

    critical_count = 0
    delayed = 0
    completed = 0
    not_started = 0
    in_progress = 0
    on_track = 0
    total_duration = 0
    weighted_progress = 0.0
    total_weight = 0
    # (date, name) of every unfinished milestone, resolved to one "next" below.
    milestone_candidates: list[tuple[str, str]] = []

    for act in activities:
        dur = act.duration_days or 0
        total_duration += dur

        progress = _str_to_float(act.progress_pct)
        if dur > 0:
            weighted_progress += progress * dur
            total_weight += dur

        if getattr(act, "is_critical", False):
            critical_count += 1

        effective_status = _effective_activity_status(
            stored_status=act.status,
            progress_pct=progress,
            end_date=act.end_date,
            today=today,
            region=project_region,
        )

        if effective_status == "delayed":
            delayed += 1
        elif effective_status == "completed":
            completed += 1
        elif effective_status == "not_started":
            not_started += 1
            on_track += 1
        elif effective_status == "in_progress":
            in_progress += 1
            on_track += 1

        if act.activity_type == "milestone" and effective_status != "completed" and act.end_date:
            milestone_candidates.append((str(act.end_date)[:10], act.name))

    progress_pct = 0.0
    if total_weight > 0:
        progress_pct = round(weighted_progress / total_weight, 1)

    # The "next" milestone is the earliest unfinished one. Prefer a date still
    # in the future; if every remaining milestone is already overdue, surface
    # the most overdue one so the team sees the slip rather than nothing.
    next_milestone: NextMilestone | None = None
    if milestone_candidates:
        milestone_candidates.sort(key=lambda m: m[0])
        today_iso = today.isoformat()
        upcoming = [m for m in milestone_candidates if m[0] >= today_iso]
        chosen = upcoming[0] if upcoming else milestone_candidates[0]
        next_milestone = NextMilestone(name=chosen[1], date=chosen[0])

    return ScheduleStatsResponse(
        total_activities=total,
        critical_count=critical_count,
        on_track=on_track,
        delayed=delayed,
        completed=completed,
        not_started=not_started,
        in_progress=in_progress,
        progress_pct=progress_pct,
        total_duration_days=total_duration,
        next_milestone=next_milestone,
    )


@router.get(
    "/work-calendar/",
    response_model=WorkCalendarResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def schedule_work_calendar(
    project_id: uuid.UUID = Query(..., description="Project to resolve the work calendar for"),
    session: SessionDep = None,  # type: ignore[assignment]
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> WorkCalendarResponse:
    """Return the resolved regional work calendar for a project.

    The schedule duration/CPM math resolves the calendar via prefix + full-label
    region maps. Exposing the resolved values here lets the UI render the true
    hours-per-day / days-per-week badge instead of re-deriving it from a smaller
    client-side map that diverges for region values like "Middle East",
    "United States", "DE_BERLIN" or "NORDIC".
    """
    await verify_project_access(project_id, _user_id, session)

    from app.modules.projects.repository import ProjectRepository

    project = await ProjectRepository(session).get_by_id(project_id)
    region = project.region if project else None
    cal = get_work_calendar(region)
    return WorkCalendarResponse(
        region=region,
        hours_per_day=cal["hours_per_day"],
        work_days_per_week=len(cal["work_days"]),
        label=cal["label"],
    )


@router.get(
    "/critical-path/",
    response_model=list[ActivityResponse],
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def critical_path_activities(
    project_id: uuid.UUID | None = Query(default=None, description="Project to retrieve critical path for"),
    schedule_id: uuid.UUID | None = Query(
        default=None,
        description="Schedule to retrieve critical path for (takes precedence over project_id)",
    ),
    session: SessionDep = None,  # type: ignore[assignment]
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[ActivityResponse]:
    """Return only critical-path activities for a schedule or across a project.

    Either ``schedule_id`` or ``project_id`` must be provided. ``schedule_id``
    takes precedence - when supplied the project is inferred from the schedule.

    Filters activities where ``is_critical=True``, ordered by early_start.
    Requires CPM calculation to have been run first.
    """
    from sqlalchemy import select

    from app.modules.schedule.models import Activity, Schedule

    if project_id is None and schedule_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either project_id or schedule_id must be provided.",
        )

    schedule_ids: list[uuid.UUID]
    if schedule_id is not None:
        # Load schedule, derive project_id from it, verify project access.
        sched = await session.get(Schedule, schedule_id)
        if sched is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schedule {schedule_id} not found",
            )
        await verify_project_access(sched.project_id, _user_id, session)
        schedule_ids = [schedule_id]
    else:
        await verify_project_access(project_id, _user_id, session)
        sched_stmt = select(Schedule.id).where(Schedule.project_id == project_id)
        sched_result = await session.execute(sched_stmt)
        schedule_ids = [row[0] for row in sched_result.all()]

    if not schedule_ids:
        return []

    act_stmt = (
        select(Activity)
        .where(Activity.schedule_id.in_(schedule_ids))
        .where(Activity.is_critical == True)  # noqa: E712
        .order_by(Activity.sort_order)
    )
    act_result = await session.execute(act_stmt)
    activities = list(act_result.scalars().all())

    # ``Activity.early_start`` is a ``String(20)`` column populated by the CPM
    # engine with integer day-offsets stringified (``"0"``, ``"1"``, ``"10"``,
    # ``"2"`` …). A plain SQL ``ORDER BY early_start`` does a lexicographic
    # sort and would produce ``"0" < "1" < "10" < "2"`` - wrong for any
    # project with >9 critical activities. Sort in Python with safe integer
    # coercion (legacy rows may also hold ISO dates or empty strings; both
    # fall through to a large sentinel so they sort last but remain stable).
    def _es_key(a: Activity) -> tuple[int, int]:
        raw = getattr(a, "early_start", None)
        try:
            return (int(str(raw)), int(getattr(a, "sort_order", 0) or 0))
        except (TypeError, ValueError):
            # Non-numeric (ISO date string, None, ""): push to the end while
            # preserving sort_order tiebreak.
            return (2**31 - 1, int(getattr(a, "sort_order", 0) or 0))

    activities.sort(key=_es_key)

    return [_activity_to_response(a) for a in activities]


# ── Project Intelligence (RFC 25) ───────────────────────────────────────────


@router.get(
    "/labor-cost-by-phase/",
    response_model=LaborCostByPhaseResponse,
    summary="Labour cost rolled up by schedule phase (RFC 25)",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_labor_cost_by_phase(
    session: SessionDep,
    _user_id: CurrentUserId,
    project_id: uuid.UUID = Query(..., description="Project scope"),
    service: ScheduleService = Depends(_get_service),
) -> LaborCostByPhaseResponse:
    """Return labour cost per WBS phase for the Estimation Dashboard."""
    await verify_project_access(project_id, _user_id, session)
    return await service.get_labor_cost_by_phase(project_id)


# ── Schedule comparison / diff (T1.3) ────────────────────────────────────────


async def _load_activities_relationships(session: SessionDep, schedule_id: uuid.UUID) -> tuple[list, list]:
    """Load all Activity + ScheduleRelationship rows for a schedule."""
    from sqlalchemy import select

    from app.modules.schedule.models import Activity, ScheduleRelationship

    acts = (await session.execute(select(Activity).where(Activity.schedule_id == schedule_id))).scalars().all()
    rels = (
        (await session.execute(select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)))
        .scalars()
        .all()
    )
    return list(acts), list(rels)


async def _load_baseline_for_project(
    session: SessionDep,
    baseline_id: uuid.UUID,
    project_id: uuid.UUID,
) -> object:
    """Load a baseline and confirm it belongs to ``project_id``.

    Existence-oracle safe: a baseline from another project 404s exactly like a
    missing one, so the id can't be enumerated across tenants.
    """
    from app.modules.schedule.models import ScheduleBaseline

    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None or baseline.project_id != project_id:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return baseline


def _diff_to_dict(result: object) -> dict:
    """Map a pure ``DiffResult`` dataclass into a JSON-safe response dict."""
    s = result.summary
    return {
        "activities": [
            {
                "key": c.key,
                "change_type": c.change_type,
                "categories": list(c.categories),
                "fields": c.fields,
                "finish_movement_days": c.finish_movement_days,
                "critical_path": c.critical_path,
                "name": c.name,
                "wbs_code": c.wbs_code,
            }
            for c in result.activities
        ],
        "relationships": [
            {
                "key": list(c.key),
                "change_type": c.change_type,
                "categories": list(c.categories),
                "fields": c.fields,
            }
            for c in result.relationships
        ],
        "calendars": [
            {"key": c.key, "change_type": c.change_type, "categories": list(c.categories)} for c in result.calendars
        ],
        "summary": {
            "net_finish_movement_days": s.net_finish_movement_days,
            "count_by_category": s.count_by_category,
            "activities_added": s.activities_added,
            "activities_removed": s.activities_removed,
            "activities_changed": s.activities_changed,
            "relationships_added": s.relationships_added,
            "relationships_removed": s.relationships_removed,
            "relationships_retyped": s.relationships_retyped,
            "relationships_relagged": s.relationships_relagged,
            "critical_path_in": s.critical_path_in,
            "critical_path_out": s.critical_path_out,
            "cost_planned_delta": str(s.cost_planned_delta),
            "cost_actual_delta": str(s.cost_actual_delta),
            "largest_slips": s.largest_slips,
        },
    }


@router.get(
    "/schedules/{schedule_id}/snapshot-envelope",
    response_model=SnapshotEnvelopeResponse,
    summary="Capture the live schedule as a comparison envelope",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_snapshot_envelope(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleService = Depends(_get_service),
) -> SnapshotEnvelopeResponse:
    """Return the current schedule flattened into the canonical diff envelope."""
    from app.modules.schedule.snapshot_envelope import live_envelope

    await _verify_schedule_owner(service, session, schedule_id, user_id)
    acts, rels = await _load_activities_relationships(session, schedule_id)
    return SnapshotEnvelopeResponse(schedule_id=schedule_id, envelope=live_envelope(acts, rels))


@router.post(
    "/schedules/{schedule_id}/diff",
    response_model=ScheduleDiffResponse,
    summary="Compare two schedule snapshots (baseline vs live, or baseline vs baseline)",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def diff_schedule(
    schedule_id: uuid.UUID,
    data: ScheduleDiffRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleService = Depends(_get_service),
) -> ScheduleDiffResponse:
    """Categorized diff between a base and a target snapshot of this schedule.

    Base is a captured baseline or an inline envelope; target defaults to the
    live schedule or another baseline. Returns per-activity, per-relationship
    and per-calendar changes plus roll-up metrics (net finish movement,
    critical-path in/out, cost deltas, largest slips). Read-only.
    """
    from app.modules.schedule.diff_engine import diff_snapshots
    from app.modules.schedule.snapshot_envelope import live_envelope, normalize_envelope

    schedule = await _verify_schedule_owner(service, session, schedule_id, user_id)
    project_id = schedule.project_id

    if data.base_baseline_id is not None:
        base_bl = await _load_baseline_for_project(session, data.base_baseline_id, project_id)
        base_env = normalize_envelope(base_bl.snapshot_data)
        base_label = base_bl.name
    elif data.base_envelope is not None:
        base_env = normalize_envelope(data.base_envelope)
        base_label = "provided"
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide base_baseline_id or base_envelope.",
        )

    if data.target_baseline_id is not None:
        target_bl = await _load_baseline_for_project(session, data.target_baseline_id, project_id)
        target_env = normalize_envelope(target_bl.snapshot_data)
        target_label = target_bl.name
    else:
        acts, rels = await _load_activities_relationships(session, schedule_id)
        target_env = live_envelope(acts, rels)
        target_label = "current"

    result = diff_snapshots(base_env, target_env)
    return ScheduleDiffResponse(
        schedule_id=schedule_id,
        base_label=base_label,
        target_label=target_label,
        **_diff_to_dict(result),
    )


# Activity codes, UDFs and saved layouts (T2.3) live on their own router file to
# keep this module readable; they mount under the same /api/v1/schedule prefix.
from app.modules.schedule.codes_router import codes_router as _codes_router  # noqa: E402

router.include_router(_codes_router)

# Progress rigor (T3.2): typed progress, weighted steps, suspend/resume,
# per-activity calendar and time-phased planned-value preview. Same prefix.
from app.modules.schedule.progress_router import progress_router as _progress_router  # noqa: E402

router.include_router(_progress_router)

# Real-time collaboration (T3.4): presence snapshot, optimistic-concurrency
# guarded activity update, and the revision-token read. Same /api/v1/schedule
# prefix. The live presence channel rides the collaboration-locks WebSocket.
from app.modules.schedule.realtime_router import realtime_router as _realtime_router  # noqa: E402

router.include_router(_realtime_router)

# Lossless schedule interchange (T1.1): neutral export / import document plus a
# normalise-on-import cleaner (DCMA-style hygiene). Same /api/v1/schedule prefix.
from app.modules.schedule.interchange_router import interchange_router as _interchange_router  # noqa: E402

router.include_router(_interchange_router)

# Persisted EVM snapshots: a read-only trend of PV / EV / BAC / SPI captured as
# the schedule data date advances. Same /api/v1/schedule prefix.
from app.modules.schedule.evm_snapshot_router import evm_snapshot_router as _evm_snapshot_router  # noqa: E402

router.include_router(_evm_snapshot_router)
