"""Schedule API routes.

Endpoints:
    POST   /schedules/                          — Create a new schedule
    GET    /schedules/?project_id=xxx           — List schedules for a project
    GET    /schedules/{id}                      — Get schedule detail
    PATCH  /schedules/{id}                      — Update schedule
    DELETE /schedules/{id}                      — Delete schedule
    POST   /schedules/{id}/activities           — Add activity to schedule
    GET    /schedules/{id}/activities           — List activities for schedule
    GET    /schedules/{id}/gantt                — Get Gantt chart data
    POST   /schedules/{id}/generate-from-boq   — Generate activities from BOQ
    POST   /schedules/{id}/calculate-cpm       — Calculate critical path
    GET    /schedules/{id}/risk-analysis       — PERT risk analysis
    PATCH  /activities/{id}                     — Update activity
    DELETE /activities/{id}                     — Delete activity
    POST   /activities/{id}/link-position       — Link BOQ position to activity
    PATCH  /activities/{id}/progress            — Update activity progress
    POST   /activities/{activity_id}/work-orders — Create work order
    GET    /work-orders/?schedule_id=xxx        — List work orders for schedule
    PATCH  /work-orders/{id}                    — Update work order
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.schedule.schemas import (
    ActivityCreate,
    ActivityResponse,
    ActivityUpdate,
    CPMCalculateRequest,
    CriticalPathResponse,
    GanttData,
    GenerateFromBOQRequest,
    LinkPositionRequest,
    ProgressUpdateRequest,
    RelationshipCreate,
    RelationshipResponse,
    RiskAnalysisResponse,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderUpdate,
)
from app.modules.schedule.service import ScheduleService, _str_to_float

router = APIRouter()


def _get_service(session: SessionDep) -> ScheduleService:
    return ScheduleService(session)


async def _verify_schedule_project_owner(
    session: SessionDep,
    project_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> None:
    """Verify the current user owns the project. Admins bypass."""
    if payload and payload.get("role") == "admin":
        return
    from app.modules.projects.repository import ProjectRepository

    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.owner_id) != user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this project")


async def _verify_schedule_owner(
    service: ScheduleService,
    session: SessionDep,
    schedule_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> object:
    """Load a schedule and verify the user owns its project. Admins bypass."""
    if payload and payload.get("role") == "admin":
        return await service.get_schedule(schedule_id)
    schedule = await service.get_schedule(schedule_id)
    from app.modules.projects.repository import ProjectRepository

    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(schedule.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.owner_id) != user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this schedule")
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
    response_model=list[ScheduleResponse],
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
) -> list[ScheduleResponse]:
    """List all schedules for a given project."""
    await _verify_schedule_project_owner(session, project_id, _user_id, payload)
    schedules, _ = await service.list_schedules_for_project(project_id, offset=offset, limit=limit)
    return [ScheduleResponse.model_validate(s) for s in schedules]


@router.get(
    "/schedules/{schedule_id}",
    response_model=ScheduleResponse,
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
    "/schedules/{schedule_id}/activities",
    response_model=ActivityResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_activity(
    schedule_id: uuid.UUID,
    data: ActivityCreate,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Add a new activity to a schedule.

    The schedule_id in the URL takes precedence over the body field.
    """
    # Override body schedule_id with URL path parameter
    data.schedule_id = schedule_id
    activity = await service.create_activity(data)
    return _activity_to_response(activity)


@router.get(
    "/schedules/{schedule_id}/activities",
    response_model=list[ActivityResponse],
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_activities(
    schedule_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ScheduleService = Depends(_get_service),
) -> list[ActivityResponse]:
    """List all activities for a schedule, ordered by sort_order."""
    activities, _ = await service.list_activities_for_schedule(schedule_id, offset=offset, limit=limit)
    return [_activity_to_response(a) for a in activities]


@router.get(
    "/schedules/{schedule_id}/gantt",
    response_model=GanttData,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_gantt_data(
    schedule_id: uuid.UUID,
    service: ScheduleService = Depends(_get_service),
) -> GanttData:
    """Get structured Gantt chart data for a schedule."""
    return await service.get_gantt_data(schedule_id)


# ── CPM & BOQ Generation ───────────────────────────────────────────────────


@router.post(
    "/schedules/{schedule_id}/generate-from-boq",
    response_model=list[ActivityResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def generate_from_boq(
    schedule_id: uuid.UUID,
    body: GenerateFromBOQRequest,
    service: ScheduleService = Depends(_get_service),
) -> list[ActivityResponse]:
    """Generate schedule activities from a BOQ.

    Creates one activity per BOQ section with cost-proportional durations
    and sequential finish-to-start dependencies.
    """
    import traceback as _tb

    try:
        await service.generate_from_boq(schedule_id, body.boq_id, body.total_project_days)
        # Re-fetch activities to avoid greenlet/lazy-loading issues
        activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)
        return [_activity_to_response(a) for a in activities]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("generate_from_boq failed: %s\n%s", exc, _tb.format_exc())
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/schedules/{schedule_id}/calculate-cpm",
    response_model=CriticalPathResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def calculate_cpm(
    schedule_id: uuid.UUID,
    service: ScheduleService = Depends(_get_service),
) -> CriticalPathResponse:
    """Calculate the critical path (CPM forward/backward pass).

    Returns early/late start/finish, total float, and critical path for all
    activities. Updates activity colors: red for critical, blue for non-critical.
    """
    return await service.calculate_critical_path(schedule_id)


@router.get(
    "/schedules/{schedule_id}/risk-analysis",
    response_model=RiskAnalysisResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_risk_analysis(
    schedule_id: uuid.UUID,
    service: ScheduleService = Depends(_get_service),
) -> RiskAnalysisResponse:
    """Get PERT-based risk analysis with P50, P80, P95 duration estimates.

    Computes optimistic/pessimistic durations for each activity and derives
    project-level probability estimates for schedule completion.
    """
    return await service.get_risk_analysis(schedule_id)


@router.patch(
    "/activities/{activity_id}",
    response_model=ActivityResponse,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_activity(
    activity_id: uuid.UUID,
    data: ActivityUpdate,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Update a schedule activity. Recalculates duration if dates changed."""
    activity = await service.update_activity(activity_id, data)
    return _activity_to_response(activity)


@router.delete(
    "/activities/{activity_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("schedule.delete"))],
)
async def delete_activity(
    activity_id: uuid.UUID,
    service: ScheduleService = Depends(_get_service),
) -> None:
    """Delete an activity and its work orders."""
    await service.delete_activity(activity_id)


@router.post(
    "/activities/{activity_id}/link-position",
    response_model=ActivityResponse,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def link_boq_position(
    activity_id: uuid.UUID,
    body: LinkPositionRequest,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Link a BOQ position to an activity."""
    activity = await service.link_boq_position(activity_id, body.boq_position_id)
    return _activity_to_response(activity)


@router.patch(
    "/activities/{activity_id}/progress",
    response_model=ActivityResponse,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_activity_progress(
    activity_id: uuid.UUID,
    body: ProgressUpdateRequest,
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Update activity progress percentage. Auto-adjusts status."""
    activity = await service.update_progress(activity_id, body.progress_pct)
    return _activity_to_response(activity)


# ── Work Order CRUD ──────────────────────────────────────────────────────────


@router.post(
    "/activities/{activity_id}/work-orders",
    response_model=WorkOrderResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("schedule.work_orders.manage"))],
)
async def create_work_order(
    activity_id: uuid.UUID,
    data: WorkOrderCreate,
    service: ScheduleService = Depends(_get_service),
) -> WorkOrderResponse:
    """Create a new work order for an activity.

    The activity_id in the URL takes precedence over the body field.
    """
    # Override body activity_id with URL path parameter
    data.activity_id = activity_id
    work_order = await service.create_work_order(data)
    return _work_order_to_response(work_order)


@router.get(
    "/work-orders/",
    response_model=list[WorkOrderResponse],
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_work_orders(
    schedule_id: uuid.UUID = Query(..., description="Filter work orders by schedule"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ScheduleService = Depends(_get_service),
) -> list[WorkOrderResponse]:
    """List all work orders for a schedule."""
    work_orders, _ = await service.list_work_orders_for_schedule(schedule_id, offset=offset, limit=limit)
    return [_work_order_to_response(wo) for wo in work_orders]


@router.patch(
    "/work-orders/{work_order_id}",
    response_model=WorkOrderResponse,
    dependencies=[Depends(RequirePermission("schedule.work_orders.manage"))],
)
async def update_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderUpdate,
    service: ScheduleService = Depends(_get_service),
) -> WorkOrderResponse:
    """Update a work order."""
    work_order = await service.update_work_order(work_order_id, data)
    return _work_order_to_response(work_order)


# ── Schedule Relationships (Phase 13) ───────────────────────────────────────


@router.post(
    "/schedules/{schedule_id}/relationships",
    response_model=RelationshipResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_relationship(
    schedule_id: uuid.UUID,
    data: RelationshipCreate,
    session: SessionDep,
) -> RelationshipResponse:
    """Create a CPM dependency relationship between two activities."""
    from app.modules.schedule.models import ScheduleRelationship

    rel = ScheduleRelationship(
        schedule_id=schedule_id,
        predecessor_id=data.predecessor_id,
        successor_id=data.successor_id,
        relationship_type=data.relationship_type,
        lag_days=data.lag_days,
    )
    session.add(rel)
    await session.flush()
    return RelationshipResponse.model_validate(rel)


@router.get(
    "/schedules/{schedule_id}/relationships",
    response_model=list[RelationshipResponse],
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_relationships(
    schedule_id: uuid.UUID,
    session: SessionDep,
) -> list[RelationshipResponse]:
    """List all CPM relationships for a schedule."""
    from sqlalchemy import select

    from app.modules.schedule.models import ScheduleRelationship

    stmt = select(ScheduleRelationship).where(
        ScheduleRelationship.schedule_id == schedule_id
    )
    result = await session.execute(stmt)
    rels = list(result.scalars().all())
    return [RelationshipResponse.model_validate(r) for r in rels]


@router.delete(
    "/relationships/{relationship_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def delete_relationship(
    relationship_id: uuid.UUID,
    session: SessionDep,
) -> None:
    """Delete a schedule relationship."""
    from sqlalchemy import delete

    from app.modules.schedule.models import ScheduleRelationship

    stmt = delete(ScheduleRelationship).where(
        ScheduleRelationship.id == relationship_id
    )
    await session.execute(stmt)


# ── CPM Calculation (Phase 13 — uses core/cpm.py engine) ────────────────────


@router.post(
    "/schedule/cpm/calculate",
    response_model=CriticalPathResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def calculate_cpm_full(
    schedule_id: uuid.UUID = Query(..., description="Schedule to run CPM on"),
    body: CPMCalculateRequest | None = None,
    session: SessionDep = None,
    service: ScheduleService = Depends(_get_service),
) -> CriticalPathResponse:
    """Run full CPM calculation using the core engine and store results.

    Reads activities and explicit ScheduleRelationship records (plus inline
    dependency JSON) to build the network.  Runs forward/backward pass,
    computes floats, identifies the critical path, persists CPM results on
    each activity, and returns the full analysis.
    """
    from sqlalchemy import select

    from app.core.cpm import calculate_cpm
    from app.modules.schedule.models import ScheduleRelationship
    from app.modules.schedule.schemas import CPMActivityResult

    schedule = await service.get_schedule(schedule_id)
    activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)

    if not activities:
        raise HTTPException(status_code=404, detail="Schedule has no activities")

    # Build activity dicts for CPM engine
    act_dicts = []
    for act in activities:
        act_dicts.append({
            "id": str(act.id),
            "duration": act.duration_days or 0,
            "name": act.name,
        })

    # Collect relationships from both ScheduleRelationship table and inline deps
    rel_dicts: list[dict] = []

    # 1. Explicit ScheduleRelationship records
    rel_stmt = select(ScheduleRelationship).where(
        ScheduleRelationship.schedule_id == schedule_id
    )
    rel_result = await session.execute(rel_stmt)
    for r in rel_result.scalars().all():
        rel_dicts.append({
            "predecessor_id": str(r.predecessor_id),
            "successor_id": str(r.successor_id),
            "type": r.relationship_type,
            "lag": r.lag_days,
        })

    # 2. Inline JSON dependencies from each activity
    for act in activities:
        deps = act.dependencies or []
        for dep in deps:
            if isinstance(dep, dict):
                pred_id = dep.get("activity_id", "")
                rel_dicts.append({
                    "predecessor_id": str(pred_id),
                    "successor_id": str(act.id),
                    "type": dep.get("type", "FS"),
                    "lag": dep.get("lag_days", 0),
                })
            elif isinstance(dep, str):
                rel_dicts.append({
                    "predecessor_id": dep,
                    "successor_id": str(act.id),
                    "type": "FS",
                    "lag": 0,
                })

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
