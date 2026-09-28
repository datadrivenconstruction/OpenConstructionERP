# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resources API routes.

Mounted at ``/api/v1/resources/``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.resources.resource_depth_router import resource_depth_router
from app.modules.resources.schemas import (
    AssignmentCreate,
    AssignmentProposeRequest,
    AssignmentResponse,
    AssignmentUpdate,
    AssignmentValidationReport,
    AvailabilityWindowCreate,
    AvailabilityWindowResponse,
    AvailabilityWindowUpdate,
    BoardConflict,
    BoardEntry,
    BoardResponse,
    CertificationCreate,
    CertificationResponse,
    CertificationUpdate,
    ConflictDetail,
    PortfolioCapacityResponse,
    PortfolioLevelingResponse,
    ResourceCreate,
    ResourceDashboardResponse,
    ResourceLinkCreate,
    ResourceLinkResponse,
    ResourceLinkUpdate,
    ResourceListResponse,
    ResourceRequestCreate,
    ResourceRequestFulfill,
    ResourceRequestResponse,
    ResourceRequestUpdate,
    ResourceResponse,
    ResourceSkillCreate,
    ResourceSkillResponse,
    ResourceUpdate,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)
from app.modules.resources.service import (
    ResourceConflictError,
    ResourcesService,
    SkillMismatchError,
)

router = APIRouter(tags=["resources"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ResourcesService:
    return ResourcesService(session)


# T3.1 resource-depth endpoints (rates, curves, native units, histogram).
router.include_router(resource_depth_router)


# ── Resources ─────────────────────────────────────────────────────────────


@router.get("/resources/", response_model=ResourceListResponse)
async def list_resources(
    _perm: None = Depends(RequirePermission("resources.read")),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    project_id: uuid.UUID | None = Query(default=None),
    service: ResourcesService = Depends(_get_service),
) -> ResourceListResponse:
    """List resources; ``project_id`` narrows to that project's own roster.

    The narrowed form is what a site surface wants - the crews homed on this
    project plus the unhomed company pool. Omitting it keeps the tenant-wide
    register the resources page reads.

    ``total`` is what the filters matched, not the page, so a picker capped at
    500 can say it is showing 500 of however many there are. The service has
    always returned that count and this route used to discard it.
    """
    items, total = await service.list_resources(
        offset=offset,
        limit=limit,
        resource_type=type_filter,
        resource_status=status_filter,
        project_id=project_id,
    )
    return ResourceListResponse(
        items=[ResourceResponse.model_validate(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/resources/", response_model=ResourceResponse, status_code=201)
async def create_resource(
    data: ResourceCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("resources.create")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceResponse:
    resource = await service.create_resource(data, user_id=user_id)
    return ResourceResponse.model_validate(resource)


@router.get("/resources/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceResponse:
    resource = await service.get_resource(resource_id)
    return ResourceResponse.model_validate(resource)


@router.patch("/resources/{resource_id}", response_model=ResourceResponse)
async def update_resource(
    resource_id: uuid.UUID,
    data: ResourceUpdate,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceResponse:
    resource = await service.update_resource(resource_id, data)
    return ResourceResponse.model_validate(resource)


@router.delete("/resources/{resource_id}", status_code=204)
async def delete_resource(
    resource_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    await service.delete_resource(resource_id)


@router.get(
    "/resources/{resource_id}/dashboard",
    response_model=ResourceDashboardResponse,
)
async def resource_dashboard(
    resource_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceDashboardResponse:
    payload = await service.resource_dashboard(resource_id)
    return ResourceDashboardResponse(
        resource=ResourceResponse.model_validate(payload["resource"]),
        active_assignments=[AssignmentResponse.model_validate(a) for a in payload["active_assignments"]],
        upcoming_assignments=[AssignmentResponse.model_validate(a) for a in payload["upcoming_assignments"]],
        certifications=[CertificationResponse.model_validate(c) for c in payload["certifications"]],
        skills=[ResourceSkillResponse.model_validate(s) for s in payload["skills"]],
        expiring_certifications_count=payload["expiring_certifications_count"],
        utilization_30d=payload["utilization_30d"],
    )


# ── Skills ───────────────────────────────────────────────────────────────


@router.get("/skills/", response_model=list[SkillResponse])
async def list_skills(
    _perm: None = Depends(RequirePermission("resources.read")),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    category: str | None = Query(default=None),
    service: ResourcesService = Depends(_get_service),
) -> list[SkillResponse]:
    items, _ = await service.list_skills(offset=offset, limit=limit, category=category)
    return [SkillResponse.model_validate(i) for i in items]


@router.post("/skills/", response_model=SkillResponse, status_code=201)
async def create_skill(
    data: SkillCreate,
    _perm: None = Depends(RequirePermission("resources.create")),
    service: ResourcesService = Depends(_get_service),
) -> SkillResponse:
    skill = await service.create_skill(data)
    return SkillResponse.model_validate(skill)


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> SkillResponse:
    skill = await service.get_skill(skill_id)
    return SkillResponse.model_validate(skill)


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: uuid.UUID,
    data: SkillUpdate,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> SkillResponse:
    skill = await service.update_skill(skill_id, data)
    return SkillResponse.model_validate(skill)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    await service.delete_skill(skill_id)


# ── ResourceSkill (sub-resource of Resource) ─────────────────────────────


@router.post(
    "/resources/{resource_id}/skills",
    response_model=ResourceSkillResponse,
    status_code=201,
)
async def attach_skill(
    resource_id: uuid.UUID,
    data: ResourceSkillCreate,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceSkillResponse:
    link = await service.attach_skill(resource_id, data)
    return ResourceSkillResponse.model_validate(link)


@router.get("/resources/{resource_id}/skills", response_model=list[ResourceSkillResponse])
async def list_resource_skills(
    resource_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[ResourceSkillResponse]:
    rows = await service.list_resource_skills(resource_id)
    return [ResourceSkillResponse.model_validate(r) for r in rows]


@router.delete("/resources/{resource_id}/skills/{skill_id}", status_code=204)
async def detach_skill(
    resource_id: uuid.UUID,
    skill_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    await service.detach_skill(resource_id, skill_id)


# ── Certifications ──────────────────────────────────────────────────────


@router.get("/certifications/", response_model=list[CertificationResponse])
async def list_certifications_for_resource(
    resource_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[CertificationResponse]:
    rows = await service.list_certifications_for_resource(resource_id)
    return [CertificationResponse.model_validate(r) for r in rows]


@router.get("/certifications/expiring", response_model=list[CertificationResponse])
async def list_expiring_certifications(
    days: int = Query(default=60, ge=1, le=365),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[CertificationResponse]:
    rows = await service.list_expiring_certifications(days=days)
    return [CertificationResponse.model_validate(r) for r in rows]


@router.post("/certifications/", response_model=CertificationResponse, status_code=201)
async def create_certification(
    data: CertificationCreate,
    _perm: None = Depends(RequirePermission("resources.create")),
    service: ResourcesService = Depends(_get_service),
) -> CertificationResponse:
    cert = await service.create_certification(data)
    return CertificationResponse.model_validate(cert)


@router.get("/certifications/{cert_id}", response_model=CertificationResponse)
async def get_certification(
    cert_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> CertificationResponse:
    cert = await service.get_certification(cert_id)
    return CertificationResponse.model_validate(cert)


@router.patch("/certifications/{cert_id}", response_model=CertificationResponse)
async def update_certification(
    cert_id: uuid.UUID,
    data: CertificationUpdate,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> CertificationResponse:
    cert = await service.update_certification(cert_id, data)
    return CertificationResponse.model_validate(cert)


@router.delete("/certifications/{cert_id}", status_code=204)
async def delete_certification(
    cert_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    await service.delete_certification(cert_id)


# ── AvailabilityWindow ─────────────────────────────────────────────────


@router.get("/availability/", response_model=list[AvailabilityWindowResponse])
async def list_windows(
    resource_id: uuid.UUID = Query(...),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[AvailabilityWindowResponse]:
    rows = await service.list_windows(resource_id, start_at=start_at, end_at=end_at)
    return [AvailabilityWindowResponse.model_validate(r) for r in rows]


@router.post("/availability/", response_model=AvailabilityWindowResponse, status_code=201)
async def create_window(
    data: AvailabilityWindowCreate,
    _perm: None = Depends(RequirePermission("resources.create")),
    service: ResourcesService = Depends(_get_service),
) -> AvailabilityWindowResponse:
    window = await service.create_window(data)
    return AvailabilityWindowResponse.model_validate(window)


@router.get("/availability/{window_id}", response_model=AvailabilityWindowResponse)
async def get_window(
    window_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> AvailabilityWindowResponse:
    window = await service.get_window(window_id)
    return AvailabilityWindowResponse.model_validate(window)


@router.patch("/availability/{window_id}", response_model=AvailabilityWindowResponse)
async def update_window(
    window_id: uuid.UUID,
    data: AvailabilityWindowUpdate,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> AvailabilityWindowResponse:
    window = await service.update_window(window_id, data)
    return AvailabilityWindowResponse.model_validate(window)


@router.delete("/availability/{window_id}", status_code=204)
async def delete_window(
    window_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    await service.delete_window(window_id)


# ── Assignments ────────────────────────────────────────────────────────


@router.get("/assignments/", response_model=list[AssignmentResponse])
async def list_assignments_for_resource(
    resource_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
    activity_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[AssignmentResponse]:
    items, _ = await service.list_assignments_for_resource(
        resource_id,
        offset=offset,
        limit=limit,
        assignment_status=status_filter,
        activity_id=activity_id,
    )
    return [AssignmentResponse.model_validate(i) for i in items]


@router.get("/assignments/by-activity/{activity_id}", response_model=list[AssignmentResponse])
async def list_assignments_for_activity(
    activity_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[AssignmentResponse]:
    """Who is booked on one schedule activity.

    ``project_id`` is required, not optional: it is the scope the caller's
    access is verified against, and without it an activity id alone would let
    any holder of ``resources.read`` read another tenant's bookings.
    """
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_assignments_for_activity(
        activity_id,
        project_id=project_id,
        offset=offset,
        limit=limit,
        assignment_status=status_filter,
    )
    return [AssignmentResponse.model_validate(i) for i in items]


@router.post("/assignments/", response_model=AssignmentResponse, status_code=201)
async def create_assignment(
    data: AssignmentCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.assign")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    # Cross-tenant guard: any caller-supplied project_id must belong to the
    # caller (or admin). Pre-fix, ``AssignmentCreate.project_id`` was trusted
    # raw and let one tenant assign a resource to another tenant's project.
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    assignment = await service.create_assignment(data, user_id=user_id)
    return AssignmentResponse.model_validate(assignment)


@router.post(
    "/assignments/propose",
    response_model=AssignmentResponse,
    status_code=201,
)
async def propose_assignment(
    data: AssignmentProposeRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.assign")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    # Cross-tenant guard on body-supplied project_id (same as create_assignment).
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    try:
        assignment = await service.propose_assignment(data, user_id=user_id)
    except ResourceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "conflicts": [c.model_dump(mode="json") for c in exc.conflicts],
            },
        ) from exc
    except SkillMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc
    return AssignmentResponse.model_validate(assignment)


@router.get("/assignments/{assignment_id}", response_model=AssignmentResponse)
async def get_assignment(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    assignment = await service.get_assignment(assignment_id)
    # Cross-tenant guard: the assignment carries the project it belongs to, so
    # only owners / admins / team-members of that project may read it. Pre-fix
    # the by-id assignment endpoints trusted the UUID alone (IDOR).
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)
    return AssignmentResponse.model_validate(assignment)


@router.patch("/assignments/{assignment_id}", response_model=AssignmentResponse)
async def update_assignment(
    assignment_id: uuid.UUID,
    data: AssignmentUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.assign")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    assignment = await service.get_assignment(assignment_id)
    # Cross-tenant guard on the assignment's CURRENT project ...
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)
    # ... and on any attempt to MOVE it onto another project the caller cannot
    # access (data.project_id is caller-supplied - must not become a back door).
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    try:
        assignment = await service.update_assignment(assignment_id, data)
    except ResourceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "conflicts": [c.model_dump(mode="json") for c in exc.conflicts],
            },
        ) from exc
    return AssignmentResponse.model_validate(assignment)


@router.delete("/assignments/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    assignment = await service.get_assignment(assignment_id)
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)
    await service.delete_assignment(assignment_id)


@router.get("/assignments/{assignment_id}/validate", response_model=AssignmentValidationReport)
async def validate_assignment(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentValidationReport:
    """Run the ``resources`` rule set over one assignment and report findings."""
    assignment = await service.get_assignment(assignment_id)
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)
    return await service.validate_assignment(assignment_id)


@router.post("/assignments/{assignment_id}/confirm", response_model=AssignmentResponse)
async def confirm_assignment(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.confirm_assignment")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    assignment = await service.get_assignment(assignment_id)
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)
    assignment = await service.confirm_assignment(assignment_id)
    return AssignmentResponse.model_validate(assignment)


@router.post("/assignments/{assignment_id}/complete", response_model=AssignmentResponse)
async def complete_assignment(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    actual_end: datetime | None = Query(default=None),
    _perm: None = Depends(RequirePermission("resources.assign")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    assignment = await service.get_assignment(assignment_id)
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)
    assignment = await service.complete_assignment(assignment_id, actual_end=actual_end)
    return AssignmentResponse.model_validate(assignment)


@router.post("/assignments/{assignment_id}/cancel", response_model=AssignmentResponse)
async def cancel_assignment(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    reason: str = Query(default=""),
    _perm: None = Depends(RequirePermission("resources.assign")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    assignment = await service.get_assignment(assignment_id)
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)
    assignment = await service.cancel_assignment(assignment_id, reason=reason)
    return AssignmentResponse.model_validate(assignment)


# ── ResourceRequests ───────────────────────────────────────────────────


@router.get("/requests/", response_model=list[ResourceRequestResponse])
async def list_requests(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[ResourceRequestResponse]:
    # Cross-tenant guard: caller must own the project (or be admin); a 404
    # is returned otherwise so this endpoint cannot be used as a
    # project-UUID existence oracle.
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_requests(project_id, offset=offset, limit=limit, request_status=status_filter)
    return [ResourceRequestResponse.model_validate(i) for i in items]


@router.post("/requests/", response_model=ResourceRequestResponse, status_code=201)
async def create_request(
    data: ResourceRequestCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.request")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceRequestResponse:
    # Cross-tenant guard on body-supplied project_id. Pre-fix any user
    # (even a freshly-registered viewer) could file resource requests
    # against another tenant's project.
    await verify_project_access(data.project_id, user_id, session)
    req = await service.request_resource(data, user_id=user_id)
    return ResourceRequestResponse.model_validate(req)


@router.get("/requests/{request_id}", response_model=ResourceRequestResponse)
async def get_request(
    request_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceRequestResponse:
    req = await service.get_request(request_id)
    await verify_project_access(req.project_id, user_id, session)
    return ResourceRequestResponse.model_validate(req)


@router.patch("/requests/{request_id}", response_model=ResourceRequestResponse)
async def update_request(
    request_id: uuid.UUID,
    data: ResourceRequestUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceRequestResponse:
    existing = await service.get_request(request_id)
    await verify_project_access(existing.project_id, user_id, session)
    req = await service.update_request(request_id, data)
    return ResourceRequestResponse.model_validate(req)


@router.delete("/requests/{request_id}", status_code=204)
async def delete_request(
    request_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    existing = await service.get_request(request_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_request(request_id)


@router.post(
    "/requests/{request_id}/fulfill",
    response_model=AssignmentResponse,
    status_code=201,
)
async def fulfill_request(
    request_id: uuid.UUID,
    payload: ResourceRequestFulfill,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.fulfill_request")),
    service: ResourcesService = Depends(_get_service),
) -> AssignmentResponse:
    existing = await service.get_request(request_id)
    await verify_project_access(existing.project_id, user_id, session)
    try:
        assignment = await service.fulfill_request(request_id, payload, user_id=user_id)
    except ResourceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "conflicts": [c.model_dump(mode="json") for c in exc.conflicts],
            },
        ) from exc
    except SkillMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc
    return AssignmentResponse.model_validate(assignment)


# ── ResourceLinks ──────────────────────────────────────────────────────


@router.get("/links/", response_model=list[ResourceLinkResponse])
async def list_links_for_resource(
    resource_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[ResourceLinkResponse]:
    rows = await service.list_links_for_resource(resource_id)
    return [ResourceLinkResponse.model_validate(r) for r in rows]


@router.post("/links/", response_model=ResourceLinkResponse, status_code=201)
async def create_link(
    data: ResourceLinkCreate,
    _perm: None = Depends(RequirePermission("resources.create")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceLinkResponse:
    link = await service.create_link(data)
    return ResourceLinkResponse.model_validate(link)


@router.get("/links/{link_id}", response_model=ResourceLinkResponse)
async def get_link(
    link_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceLinkResponse:
    link = await service.get_link(link_id)
    return ResourceLinkResponse.model_validate(link)


@router.patch("/links/{link_id}", response_model=ResourceLinkResponse)
async def update_link(
    link_id: uuid.UUID,
    data: ResourceLinkUpdate,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourcesService = Depends(_get_service),
) -> ResourceLinkResponse:
    link = await service.update_link(link_id, data)
    return ResourceLinkResponse.model_validate(link)


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(
    link_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourcesService = Depends(_get_service),
) -> None:
    await service.delete_link(link_id)


# ── Board ──────────────────────────────────────────────────────────────


@router.get("/board/", response_model=BoardResponse)
async def board(
    user_id: CurrentUserId,
    session: SessionDep,
    start: datetime = Query(...),
    end: datetime = Query(...),
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> BoardResponse:
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )
    # When the caller scopes the board to a project, verify access; the
    # unscoped board (project_id=None) is the org-wide dispatcher view
    # and is gated by ``resources.read`` only.
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    entries = await service.board(start, end, project_id=project_id)
    return BoardResponse(
        period_start=start,
        period_end=end,
        project_id=project_id,
        entries=[
            BoardEntry(
                resource=ResourceResponse.model_validate(e["resource"]),
                assignments=[AssignmentResponse.model_validate(a) for a in e["assignments"]],
            )
            for e in entries
        ],
    )


@router.get("/portfolio/capacity", response_model=PortfolioCapacityResponse)
async def portfolio_capacity(
    start: datetime = Query(...),
    end: datetime = Query(...),
    bucket: str = Query(default="week", pattern=r"^(week|month)$"),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> PortfolioCapacityResponse:
    """Org-wide resource utilization heatmap for capacity planning.

    Returns, per resource per time bucket, the total allocation across every
    project plus the per-project breakdown, flagging over-allocation and
    cross-project competition. Gated by ``resources.read`` only - like the
    org-wide dispatcher board, this is a portfolio (not project-scoped) view.
    """
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )
    payload = await service.portfolio_capacity(start, end, bucket=bucket)
    return PortfolioCapacityResponse.model_validate(payload)


@router.get("/portfolio/leveling", response_model=PortfolioLevelingResponse)
async def portfolio_leveling(
    user_id: CurrentUserId,
    session: SessionDep,
    start: datetime = Query(...),
    end: datetime = Query(...),
    bucket: str = Query(default="week", pattern=r"^(week|month)$"),
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> PortfolioLevelingResponse:
    """Read-only portfolio resource-leveling grid with overload flags + suggestions.

    Aggregates each resource's committed allocation per time bucket across every
    project (or one project when ``project_id`` is given). A bucket is flagged
    over-allocated only when the resource's declared ``capacity_percent`` is
    exceeded; resources with no declared capacity are returned as
    ``capacity_unknown`` and never as overloaded. For each overloaded bucket a
    leveling suggestion (shift / spread) is attached. Nothing is moved - the
    planner confirms each action. The unscoped (portfolio) view is gated by
    ``resources.read`` like the org-wide dispatcher board; the project-scoped
    view additionally verifies access to that project so it cannot be used as a
    cross-tenant oracle.
    """
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    payload = await service.portfolio_leveling(start, end, bucket=bucket, project_id=project_id)
    return PortfolioLevelingResponse.model_validate(payload)


@router.get("/board/conflicts", response_model=list[BoardConflict])
async def board_conflicts(
    start: datetime = Query(...),
    end: datetime = Query(...),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[BoardConflict]:
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )
    rows = await service.board_conflicts(start, end)
    return [
        BoardConflict(
            resource_id=r["resource_id"],
            resource_name=r["resource_name"],
            conflicts=[
                c if isinstance(c, ConflictDetail) else ConflictDetail.model_validate(c) for c in r["conflicts"]
            ],
        )
        for r in rows
    ]


# ── Skill-matrix ranked candidates ───────────────────────────────────────


@router.post("/candidates/rank")
async def rank_candidates(
    payload: dict,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> list[dict]:
    """Return ranked candidate resources scored on skills × availability × proximity.

    Body:
        required_skill_ids: list[uuid] - required skills
        start: ISO datetime
        end: ISO datetime
        home_project_id: optional uuid - for proximity bonus
        weight_skill / weight_availability / weight_proximity: optional floats
        limit: optional int (default 20)
    """
    try:
        skill_ids = [uuid.UUID(str(s)) for s in (payload.get("required_skill_ids") or [])]
        start = datetime.fromisoformat(str(payload["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(payload["end"]).replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid payload: {exc}",
        ) from exc
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )
    home_pid_raw = payload.get("home_project_id")
    home_pid: uuid.UUID | None = None
    if home_pid_raw:
        try:
            home_pid = uuid.UUID(str(home_pid_raw))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid home_project_id: {exc}",
            ) from exc

    # Guard the numeric tuning knobs. Previously a non-numeric
    # ``weight_*`` / ``limit`` (e.g. "high", null, a list) reached a bare
    # ``float()`` / ``int()`` and surfaced as an unhandled 500. Parse each
    # explicitly and answer with a 400 so the client sees actionable input
    # feedback instead of a server error.
    def _coerce_weight(key: str, default: float) -> float:
        raw = payload.get(key)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {key}: expected a number",
            ) from exc

    weight_skill = _coerce_weight("weight_skill", 0.6)
    weight_availability = _coerce_weight("weight_availability", 0.3)
    weight_proximity = _coerce_weight("weight_proximity", 0.1)

    limit_raw = payload.get("limit")
    if limit_raw is None or limit_raw == "":
        limit = 20
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid limit: expected an integer",
            ) from exc
        if limit < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid limit: must be >= 1",
            )

    return await service.rank_candidates(
        skill_ids,
        start,
        end,
        home_project_id=home_pid,
        weight_skill=weight_skill,
        weight_availability=weight_availability,
        weight_proximity=weight_proximity,
        limit=limit,
    )


# ── Certification expiry scan + event publish ────────────────────────────


@router.post("/certifications/expiry-scan")
async def cert_expiry_scan(
    payload: dict | None = None,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourcesService = Depends(_get_service),
) -> dict:
    """Scan expiring certifications and emit ``resources.cert_expiring`` events.

    Body (optional):
        windows_days: list[int] - default [60, 30, 14, 7]
        emit: bool - when true, publish events; when false, just preview.
    """
    body = payload or {}
    windows = body.get("windows_days") or [60, 30, 14, 7]
    try:
        windows_tuple = tuple(int(w) for w in windows if int(w) > 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid_windows_days:{exc}",
        ) from exc
    emit = bool(body.get("emit", True))
    if emit:
        emitted = await service.emit_expiry_events(windows_days=windows_tuple)
        buckets = await service.scan_expiring_certifications(windows_days=windows_tuple)
        return {
            "emitted": emitted,
            "buckets": {
                str(w): [
                    {
                        "certification_id": str(c.id),
                        "resource_id": str(c.resource_id),
                        "cert_type": c.cert_type,
                        "valid_until": c.valid_until,
                    }
                    for c in items
                ]
                for w, items in buckets.items()
            },
        }
    buckets = await service.scan_expiring_certifications(windows_days=windows_tuple)
    return {
        "emitted": 0,
        "buckets": {
            str(w): [
                {
                    "certification_id": str(c.id),
                    "resource_id": str(c.resource_id),
                    "cert_type": c.cert_type,
                    "valid_until": c.valid_until,
                }
                for c in items
            ]
            for w, items in buckets.items()
        },
    }


# ── Time-card / time-sheet import ────────────────────────────────────────


@router.post("/timecards/import", status_code=200)
async def import_timecards(
    payload: dict,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.assign")),
    service: ResourcesService = Depends(_get_service),
) -> dict:
    """Import a batch of time-card rows as completed Assignments.

    Body:
        rows: list[dict] - each row needs resource_code or resource_id,
            start_at, end_at, plus optional project_id, allocation_percent,
            cost_rate, currency, notes.
        default_status: optional - defaults to "completed".
    """
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rows must be a list of dicts",
        )
    default_status = str(payload.get("default_status") or "completed")
    if default_status not in ("completed", "confirmed", "proposed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_status must be one of completed|confirmed|proposed",
        )

    # IDOR guard - rows may carry a body-supplied project_id; verify the caller
    # can access each distinct project before importing assignments into it.
    seen_projects: set[str] = set()
    for _row in rows:
        pid = _row.get("project_id") if isinstance(_row, dict) else None
        if not pid or str(pid) in seen_projects:
            continue
        seen_projects.add(str(pid))
        try:
            pid_uuid = uuid.UUID(str(pid))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid project_id in timecard row: {pid}",
            )
        await verify_project_access(pid_uuid, user_id, session)

    return await service.import_timecards(rows, default_status=default_status, user_id=user_id)
