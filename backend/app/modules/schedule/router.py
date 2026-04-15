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

import csv
import io
import logging
import uuid
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule.schemas import (
    ActivityBimLinkRequest,
    ActivityCreate,
    ActivityResponse,
    ActivityUpdate,
    BaselineCreate,
    BaselineResponse,
    BaselineUpdate,
    CPMCalculateRequest,
    CriticalPathResponse,
    GanttData,
    GenerateFromBOQRequest,
    ImportResult,
    LinkPositionRequest,
    ProgressUpdateCreate,
    ProgressUpdateEdit,
    ProgressUpdateRequest,
    ProgressUpdateResponse,
    RelationshipCreate,
    RelationshipResponse,
    RiskAnalysisResponse,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleStatsResponse,
    ScheduleUpdate,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderUpdate,
)
from app.modules.schedule.service import ScheduleService, _str_to_float, compute_duration

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
        # Constraint, code, BIM fields
        constraint_type=getattr(activity, "constraint_type", None),
        constraint_date=getattr(activity, "constraint_date", None),
        activity_code=getattr(activity, "activity_code", None),
        bim_element_ids=getattr(activity, "bim_element_ids", None),
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
    response_model=list[ScheduleResponse],
    summary="List schedules",
    description="List all schedules for a project. Requires project_id query parameter.",
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
    "/schedules/{schedule_id}/activities/",
    response_model=list[ActivityResponse],
    summary="List activities",
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
    "/schedules/{schedule_id}/gantt/",
    response_model=GanttData,
    summary="Get Gantt chart data",
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
    "/schedules/{schedule_id}/calculate-cpm/",
    response_model=CriticalPathResponse,
    summary="Calculate critical path (CPM)",
    description="Run CPM forward/backward pass on a schedule. Returns early/late start/finish, "
    "total float, and critical path. Updates activity colors (red=critical, blue=non-critical).",
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
    summary="Update activity",
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
    summary="Delete activity",
    dependencies=[Depends(RequirePermission("schedule.delete"))],
)
async def delete_activity(
    activity_id: uuid.UUID,
    service: ScheduleService = Depends(_get_service),
) -> None:
    """Delete an activity and its work orders."""
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
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Link a BOQ position to an activity."""
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
    service: ScheduleService = Depends(_get_service),
) -> ActivityResponse:
    """Update activity progress percentage. Auto-adjusts status."""
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
    await _verify_schedule_owner(
        service, session, activity.schedule_id, _user_id, payload
    )
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
    project_id: uuid.UUID = Query(
        ..., description="Project scope for the search"
    ),
    service: ScheduleService = Depends(_get_service),
) -> list[ActivityResponse]:
    """Reverse query: return every activity in ``project_id`` whose
    ``bim_element_ids`` array contains ``element_id``.
    """
    await _verify_schedule_project_owner(session, project_id, _user_id, payload)
    activities = await service.get_activities_for_bim_element(
        element_id, project_id
    )
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
    summary="List work orders",
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
    summary="Update work order",
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
) -> RelationshipResponse:
    """Create a CPM dependency relationship between two activities.

    Validates:
    - predecessor and successor are not the same activity
    - no circular dependency would be created
    """
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
    stmt = select(ScheduleRelationship).where(
        ScheduleRelationship.schedule_id == schedule_id
    )
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
                    "Adding this dependency would create a circular reference. "
                    "Check the dependency chain for cycles."
                ),
            )
        if current in visited:
            continue
        visited.add(current)
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                queue.append(neighbor)

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
    "/schedules/{schedule_id}/relationships/",
    response_model=list[RelationshipResponse],
    summary="List CPM relationships",
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
    summary="Delete relationship",
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
    "/schedule/cpm/calculate/",
    response_model=CriticalPathResponse,
    summary="Run full CPM calculation",
    description="Full CPM calculation using the core engine. Reads activities and "
    "ScheduleRelationship records, runs forward/backward pass, computes floats, "
    "identifies the critical path, and persists results on each activity.",
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
) -> BaselineResponse:
    """Create a schedule baseline snapshot."""
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
) -> BaselineResponse:
    """Get a single baseline by ID."""
    from app.modules.schedule.models import ScheduleBaseline

    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return BaselineResponse.model_validate(baseline)


@router.patch(
    "/baselines/{baseline_id}",
    response_model=BaselineResponse,
    summary="Update baseline",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_baseline(
    baseline_id: uuid.UUID,
    data: BaselineUpdate,
    session: SessionDep,
) -> BaselineResponse:
    """Update a baseline (name, is_active, metadata)."""
    from sqlalchemy import update

    from app.modules.schedule.models import ScheduleBaseline

    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline not found")

    updates = data.model_dump(exclude_unset=True)
    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")
    if updates:
        stmt = (
            update(ScheduleBaseline)
            .where(ScheduleBaseline.id == baseline_id)
            .values(**updates)
        )
        await session.execute(stmt)
        await session.flush()
        session.expire_all()
        baseline = await session.get(ScheduleBaseline, baseline_id)
    return BaselineResponse.model_validate(baseline)


@router.delete(
    "/baselines/{baseline_id}",
    status_code=204,
    summary="Delete baseline",
    dependencies=[Depends(RequirePermission("schedule.delete"))],
)
async def delete_baseline(
    baseline_id: uuid.UUID,
    session: SessionDep,
) -> None:
    """Delete a baseline."""
    from app.modules.schedule.models import ScheduleBaseline

    baseline = await session.get(ScheduleBaseline, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline not found")
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
) -> ProgressUpdateResponse:
    """Create a progress update record."""
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
) -> ProgressUpdateResponse:
    """Get a single progress update by ID."""
    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    record = await session.get(ProgressUpdateModel, update_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Progress update not found")
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
) -> ProgressUpdateResponse:
    """Update a progress update record."""
    from sqlalchemy import update

    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    record = await session.get(ProgressUpdateModel, update_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Progress update not found")

    updates = data.model_dump(exclude_unset=True)
    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")
    if updates:
        stmt = (
            update(ProgressUpdateModel)
            .where(ProgressUpdateModel.id == update_id)
            .values(**updates)
        )
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
) -> None:
    """Delete a progress update record."""
    from app.modules.schedule.models import ProgressUpdate as ProgressUpdateModel

    record = await session.get(ProgressUpdateModel, update_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Progress update not found")
    await session.delete(record)
    await session.flush()


# ── Import / Export ───────────────────────────────────────────────────────


def _parse_xer_tables(content: str) -> dict[str, list[dict[str, str]]]:
    """Parse Primavera P6 XER tab-delimited format into table dictionaries.

    XER format uses:
      %T <TABLE_NAME>     — start of a table
      %F <col1> <col2>    — field (column) names
      %R <val1> <val2>    — row values

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
    schedule_id: uuid.UUID = Query(..., description="Target schedule to import into"),
    file: UploadFile = File(...),
    session: SessionDep = None,
    service: ScheduleService = Depends(_get_service),
) -> ImportResult:
    """Import a Primavera P6 XER file into a schedule.

    Parses TASK, TASKPRED, and CALENDAR tables from the XER format and creates
    activities and relationships in the target schedule.
    """
    from app.modules.schedule.models import Activity, ScheduleRelationship

    # Verify schedule exists
    await service.get_schedule(schedule_id)

    # Read and decode file
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    tables = _parse_xer_tables(content)
    warnings: list[str] = []

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
            task_row.get("target_end_date")
            or task_row.get("act_end_date")
            or task_row.get("early_end_date")
            or ""
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
            warnings.append(
                f"Relationship {pred_task_id}->{succ_task_id}: "
                "predecessor or successor not found, skipped"
            )
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
    await service.get_schedule(schedule_id)

    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    try:
        root = ET.fromstring(content)
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
                warnings.append(
                    f"Link: predecessor UID={pred_uid} not found for task UID={uid}"
                )
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
    schedule_id: uuid.UUID = Query(..., description="Schedule to export"),
    service: ScheduleService = Depends(_get_service),
    session: SessionDep = None,
) -> StreamingResponse:
    """Export schedule activities as a CSV file.

    Columns: Activity Code, Name, WBS, Start, End, Duration, Progress, Float,
    Critical, Predecessors.
    """
    from sqlalchemy import select

    from app.modules.schedule.models import ScheduleRelationship

    # Verify schedule exists
    schedule = await service.get_schedule(schedule_id)

    # Fetch activities
    activities, _ = await service.list_activities_for_schedule(schedule_id, limit=5000)

    # Fetch relationships for predecessor lookup
    rel_stmt = select(ScheduleRelationship).where(
        ScheduleRelationship.schedule_id == schedule_id
    )
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
    writer.writerow([
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
    ])

    for act in activities:
        act_id = str(act.id)
        preds = predecessor_map.get(act_id, [])
        # Deduplicate predecessors
        preds = list(dict.fromkeys(preds))

        writer.writerow([
            act.activity_code or "",
            act.name,
            act.wbs_code,
            act.start_date,
            act.end_date,
            act.duration_days,
            _str_to_float(act.progress_pct),
            act.total_float if act.total_float is not None else "",
            "Yes" if act.is_critical else "No",
            "; ".join(preds),
        ])

    csv_content = output.getvalue()
    output.close()

    schedule_name = schedule.name.replace(" ", "_")[:40]
    filename = f"schedule_{schedule_name}.csv"

    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    from sqlalchemy import select

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

    critical_count = 0
    delayed = 0
    completed = 0
    not_started = 0
    in_progress = 0
    on_track = 0
    total_duration = 0
    weighted_progress = 0.0
    total_weight = 0

    for act in activities:
        dur = act.duration_days or 0
        total_duration += dur

        progress = _str_to_float(act.progress_pct)
        if dur > 0:
            weighted_progress += progress * dur
            total_weight += dur

        if getattr(act, "is_critical", False):
            critical_count += 1

        if act.status == "delayed":
            delayed += 1
        elif act.status == "completed":
            completed += 1
        elif act.status == "not_started":
            not_started += 1
            on_track += 1
        elif act.status == "in_progress":
            in_progress += 1
            on_track += 1

    progress_pct = 0.0
    if total_weight > 0:
        progress_pct = round(weighted_progress / total_weight, 1)

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
    )


@router.get(
    "/critical-path/",
    response_model=list[ActivityResponse],
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def critical_path_activities(
    project_id: uuid.UUID = Query(..., description="Project to retrieve critical path for"),
    session: SessionDep = None,  # type: ignore[assignment]
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[ActivityResponse]:
    """Return only critical-path activities across all schedules in a project.

    Filters activities where is_critical=True, ordered by early_start.
    Requires CPM calculation to have been run first.
    """
    await verify_project_access(project_id, _user_id, session)
    from sqlalchemy import select

    from app.modules.schedule.models import Activity, Schedule

    # Get all schedules for the project
    sched_stmt = select(Schedule.id).where(Schedule.project_id == project_id)
    sched_result = await session.execute(sched_stmt)
    schedule_ids = [row[0] for row in sched_result.all()]

    if not schedule_ids:
        return []

    act_stmt = (
        select(Activity)
        .where(Activity.schedule_id.in_(schedule_ids))
        .where(Activity.is_critical == True)  # noqa: E712
        .order_by(Activity.early_start, Activity.sort_order)
    )
    act_result = await session.execute(act_stmt)
    activities = list(act_result.scalars().all())

    return [_activity_to_response(a) for a in activities]
