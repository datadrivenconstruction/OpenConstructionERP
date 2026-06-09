# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval Routes API routes.

Endpoints (auto-mounted at ``/api/v1/approval-routes/``)::

    GET    /routes                            - list templates
    POST   /routes                            - create template
    GET    /routes/{route_id}                 - single template + steps
    PATCH  /routes/{route_id}                 - update mutable fields
    DELETE /routes/{route_id}                 - delete (rejected if instances exist)
    GET    /instances                         - list workflows (filterable)
    POST   /instances                         - start a workflow
    GET    /instances/{instance_id}           - single workflow + step states
    POST   /instances/{instance_id}/decide    - submit a decision
    POST   /instances/{instance_id}/cancel    - cancel a pending workflow

All endpoints respect project_id tenant scoping: route templates with a
``project_id`` go through :func:`verify_project_access` so a caller
cannot see / mutate routes that belong to a different project. Tenant-
wide templates (``project_id IS NULL``) are visible to everyone with
``approval_routes.read``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.approval_routes.models import (
    INSTANCE_STATUSES,
    STEP_MODES,
    TARGET_KINDS,
)
from app.modules.approval_routes.schemas import (
    CancelInstance,
    DecisionSubmit,
    InstanceCreate,
    InstanceResponse,
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    StepResponse,
    StepStateResponse,
)
from app.modules.approval_routes.service import ApprovalRouteService

router = APIRouter(tags=["approval_routes"])


def _get_service(session: SessionDep) -> ApprovalRouteService:
    return ApprovalRouteService(session)


def _safe_user_uuid(user_id: str | None) -> uuid.UUID | None:
    if not user_id:
        return None
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None


async def _route_to_response(
    route: object,
    service: ApprovalRouteService,
) -> RouteResponse:
    steps = await service.list_steps(route.id)  # type: ignore[attr-defined]
    payload = RouteResponse.model_validate(route)
    payload.steps = [StepResponse.model_validate(s) for s in steps]
    return payload


async def _instance_to_response(
    instance: object,
    service: ApprovalRouteService,
) -> InstanceResponse:
    states = await service.list_step_states(instance.id)  # type: ignore[attr-defined]
    payload = InstanceResponse.model_validate(instance)
    payload.step_states = [StepStateResponse.model_validate(s) for s in states]
    return payload


# ── Metadata ─────────────────────────────────────────────────────────


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("approval_routes.read"))],
)
async def get_meta() -> dict[str, list[str]]:
    """Expose the validated whitelists so the UI never drifts from the DB.

    The frontend builds its target-kind / mode / status pickers from this
    payload instead of hard-coding a parallel list that can fall out of
    sync with :data:`TARGET_KINDS`.
    """
    return {
        "target_kinds": list(TARGET_KINDS),
        "step_modes": list(STEP_MODES),
        "instance_statuses": list(INSTANCE_STATUSES),
    }


# ── Routes (templates) ───────────────────────────────────────────────


@router.get(
    "/routes",
    response_model=list[RouteResponse],
    dependencies=[Depends(RequirePermission("approval_routes.read"))],
)
async def list_routes(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    target_kind: str | None = Query(default=None),
    include_inactive: bool = Query(default=True),
    service: ApprovalRouteService = Depends(_get_service),
) -> list[RouteResponse]:
    """List approval-route templates.

    When ``project_id`` is supplied we gate access through the project
    guard so callers can't enumerate routes from other projects. The
    listing then includes tenant-wide templates (``project_id IS NULL``)
    plus that project's routes - matching the picker UX in consumer
    modules.

    ``include_inactive`` defaults to ``True`` (admin surface). A consumer
    picker passes ``include_inactive=false`` so users can only start a
    workflow on an active template.
    """
    if target_kind is not None and target_kind not in TARGET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown target_kind: {target_kind!r}",
        )
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)

    rows = await service.list_routes(
        project_id=project_id,
        target_kind=target_kind,
        include_inactive=include_inactive,
    )
    # Batched: one IN(...) Step fetch instead of N per-route round trips.
    steps_by_route = await service.list_steps_for_routes([r.id for r in rows])
    responses: list[RouteResponse] = []
    for r in rows:
        payload = RouteResponse.model_validate(r)
        payload.steps = [StepResponse.model_validate(s) for s in steps_by_route.get(r.id, [])]
        responses.append(payload)
    return responses


@router.post(
    "/routes",
    response_model=RouteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("approval_routes.write"))],
)
async def create_route(
    payload: RouteCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ApprovalRouteService = Depends(_get_service),
) -> RouteResponse:
    """Create a route template + its ordered steps."""
    if payload.project_id is not None:
        await verify_project_access(payload.project_id, user_id, session)
    row = await service.create_route(
        payload,
        created_by=_safe_user_uuid(user_id),
    )
    return await _route_to_response(row, service)


@router.get(
    "/routes/{route_id}",
    response_model=RouteResponse,
    dependencies=[Depends(RequirePermission("approval_routes.read"))],
)
async def get_route(
    route_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ApprovalRouteService = Depends(_get_service),
) -> RouteResponse:
    row = await service.get_route(route_id)
    if row.project_id is not None:
        await verify_project_access(row.project_id, user_id, session)
    return await _route_to_response(row, service)


@router.patch(
    "/routes/{route_id}",
    response_model=RouteResponse,
    dependencies=[Depends(RequirePermission("approval_routes.write"))],
)
async def update_route(
    route_id: uuid.UUID,
    payload: RouteUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ApprovalRouteService = Depends(_get_service),
) -> RouteResponse:
    row = await service.get_route(route_id)
    if row.project_id is not None:
        await verify_project_access(row.project_id, user_id, session)
    updated = await service.update_route(
        route_id,
        payload,
        actor_id=_safe_user_uuid(user_id),
    )
    return await _route_to_response(updated, service)


@router.delete(
    "/routes/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("approval_routes.manage"))],
)
async def delete_route(
    route_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ApprovalRouteService = Depends(_get_service),
) -> None:
    row = await service.get_route(route_id)
    if row.project_id is not None:
        await verify_project_access(row.project_id, user_id, session)
    await service.delete_route(route_id, actor_id=_safe_user_uuid(user_id))


# ── Instances (running workflows) ────────────────────────────────────


@router.get(
    "/instances",
    response_model=list[InstanceResponse],
    dependencies=[Depends(RequirePermission("approval_routes.read"))],
)
async def list_instances(
    session: SessionDep,
    user_id: CurrentUserId,
    target_kind: str | None = Query(default=None),
    target_id: uuid.UUID | None = Query(default=None),
    route_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    instance_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: ApprovalRouteService = Depends(_get_service),
) -> list[InstanceResponse]:
    """List approval instances. Filter by target / route / project / status.

    ``project_id`` scopes the listing to instances whose route belongs to
    that project (tenant-wide routes are excluded when a project filter is
    supplied, matching the per-project drill-down UX).
    """
    # When a project filter is supplied, pre-resolve that project's route
    # ids so the instance scan is actually scoped server-side instead of
    # returning every instance and discarding most of it.
    project_route_ids: set[uuid.UUID] | None = None
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        project_routes = await service.list_routes(
            project_id=project_id,
            include_inactive=True,
        )
        # Only the project's own routes (not tenant-wide) belong to the
        # project drill-down.
        project_route_ids = {r.id for r in project_routes if r.project_id == project_id}
        if not project_route_ids:
            return []

    rows = await service.list_instances(
        target_kind=target_kind,
        target_id=target_id,
        route_id=route_id,
        instance_status=instance_status,
        limit=limit,
        offset=offset,
    )
    # Tenant guard: instances are scoped through their route's
    # project_id. We resolve project_id once per route via cache to
    # keep the listing query cheap.
    project_cache: dict[uuid.UUID, uuid.UUID | None] = {}
    visible: list[object] = []
    for inst in rows:
        if project_route_ids is not None and inst.route_id not in project_route_ids:
            continue
        if inst.route_id not in project_cache:
            try:
                route = await service.get_route(inst.route_id)
                project_cache[inst.route_id] = route.project_id
            except HTTPException:
                project_cache[inst.route_id] = None
        pid = project_cache[inst.route_id]
        if pid is not None:
            try:
                await verify_project_access(pid, user_id, session)
            except HTTPException:
                continue  # Filter out cross-tenant rows silently.
        visible.append(inst)

    # Batched: one IN(...) StepState fetch for all visible instances
    # instead of N per-instance round trips.
    states_by_instance = await service.list_step_states_for_instances(
        [inst.id for inst in visible],  # type: ignore[attr-defined]
    )
    out: list[InstanceResponse] = []
    for inst in visible:
        payload = InstanceResponse.model_validate(inst)
        payload.step_states = [
            StepStateResponse.model_validate(s)
            for s in states_by_instance.get(inst.id, [])  # type: ignore[attr-defined]
        ]
        out.append(payload)
    return out


@router.post(
    "/instances",
    response_model=InstanceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("approval_routes.write"))],
)
async def start_instance(
    payload: InstanceCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ApprovalRouteService = Depends(_get_service),
) -> InstanceResponse:
    """Start a new approval workflow against a target row."""
    route = await service.get_route(payload.route_id)
    if route.project_id is not None:
        await verify_project_access(route.project_id, user_id, session)
    instance = await service.start_instance(
        payload,
        started_by=_safe_user_uuid(user_id),
    )
    return await _instance_to_response(instance, service)


@router.get(
    "/instances/{instance_id}",
    response_model=InstanceResponse,
    dependencies=[Depends(RequirePermission("approval_routes.read"))],
)
async def get_instance(
    instance_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ApprovalRouteService = Depends(_get_service),
) -> InstanceResponse:
    instance = await service.get_instance(instance_id)
    route = await service.get_route(instance.route_id)
    if route.project_id is not None:
        await verify_project_access(route.project_id, user_id, session)
    return await _instance_to_response(instance, service)


@router.post(
    "/instances/{instance_id}/decide",
    response_model=InstanceResponse,
    dependencies=[Depends(RequirePermission("approval_routes.decide"))],
)
async def submit_decision(
    instance_id: uuid.UUID,
    payload: DecisionSubmit,
    session: SessionDep,
    user_id: CurrentUserId,
    user_payload: CurrentUserPayload,
    service: ApprovalRouteService = Depends(_get_service),
) -> InstanceResponse:
    """Approve / reject the current step on an instance.

    The caller's app role (from the JWT payload) is passed through so the
    service can enforce a role-based step's approver role, not just the
    ``approval_routes.decide`` permission.
    """
    instance = await service.get_instance(instance_id)
    route = await service.get_route(instance.route_id)
    if route.project_id is not None:
        await verify_project_access(route.project_id, user_id, session)
    updated = await service.submit_decision(
        instance_id,
        payload,
        approver_id=_safe_user_uuid(user_id),
        caller_role=user_payload.get("role"),
    )
    return await _instance_to_response(updated, service)


@router.post(
    "/instances/{instance_id}/cancel",
    response_model=InstanceResponse,
    dependencies=[Depends(RequirePermission("approval_routes.manage"))],
)
async def cancel_instance(
    instance_id: uuid.UUID,
    payload: CancelInstance,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ApprovalRouteService = Depends(_get_service),
) -> InstanceResponse:
    """Cancel a pending instance."""
    instance = await service.get_instance(instance_id)
    route = await service.get_route(instance.route_id)
    if route.project_id is not None:
        await verify_project_access(route.project_id, user_id, session)
    cancelled = await service.cancel_instance(
        instance_id,
        actor_id=_safe_user_uuid(user_id),
        reason=payload.reason,
    )
    return await _instance_to_response(cancelled, service)
