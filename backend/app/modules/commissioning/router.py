# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commissioning (Cx) API routes.

Route prefix (mounted by the module loader): ``/api/v1/commissioning``.

Endpoints:
    GET    /stats?project_id=X                       - project rollup
    GET    /systems?project_id=X                     - list systems (+ readiness)
    POST   /systems/                                 - create system
    GET    /systems/{system_id}                      - get one system (+ readiness)
    PATCH  /systems/{system_id}                      - update system
    DELETE /systems/{system_id}                      - delete system
    GET    /systems/{system_id}/readiness/           - readiness breakdown
    POST   /systems/{system_id}/commission/          - gated commission action
    GET    /systems/{system_id}/checklists/          - list checklists
    POST   /systems/{system_id}/checklists/          - create checklist
    PATCH  /checklists/{checklist_id}                - update checklist
    DELETE /checklists/{checklist_id}               - delete checklist
    GET    /checklists/{checklist_id}/items/         - list items
    POST   /checklists/{checklist_id}/items/         - create item
    PATCH  /items/{item_id}                          - update item
    POST   /items/{item_id}/result/                  - set pass/fail/na result
    DELETE /items/{item_id}                          - delete item
    GET    /systems/{system_id}/issues/              - list issues
    POST   /systems/{system_id}/issues/              - create issue
    PATCH  /issues/{issue_id}                        - update issue
    DELETE /issues/{issue_id}                        - delete issue

Permissions: reads require ``commissioning.read`` (VIEWER), every mutation
requires ``commissioning.write`` (EDITOR), and the gated commission action
requires ``commissioning.commission`` (MANAGER). Mutating handlers commit the
session before returning so the write is durable and any post-write readiness
read reflects the committed state.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.commissioning.schemas import (
    ChecklistCreate,
    ChecklistResponse,
    ChecklistUpdate,
    CommissionRequest,
    CxStatsResponse,
    IssueCreate,
    IssueResponse,
    IssueUpdate,
    ItemCreate,
    ItemResponse,
    ItemResultRequest,
    ItemUpdate,
    ReadinessSummary,
    SystemCreate,
    SystemResponse,
    SystemUpdate,
)
from app.modules.commissioning.service import CommissioningService

router = APIRouter(tags=["commissioning"])
logger = logging.getLogger(__name__)

_READ = Depends(RequirePermission("commissioning.read"))
_WRITE = Depends(RequirePermission("commissioning.write"))
_COMMISSION = Depends(RequirePermission("commissioning.commission"))


def _get_service(session: SessionDep) -> CommissioningService:
    return CommissioningService(session)


def _system_to_response(system: Any, readiness: dict[str, Any] | None = None) -> SystemResponse:
    """Build a SystemResponse from an ORM system plus an optional readiness dict."""
    return SystemResponse(
        id=system.id,
        project_id=system.project_id,
        name=system.name,
        system_type=system.system_type,
        tag=system.tag,
        location=system.location,
        description=system.description,
        status=system.status,
        commissioned_at=system.commissioned_at,
        commissioned_by=system.commissioned_by,
        created_by=system.created_by,
        metadata=getattr(system, "metadata_", {}),
        readiness=ReadinessSummary(**readiness) if readiness is not None else None,
        created_at=system.created_at,
        updated_at=system.updated_at,
    )


def _checklist_to_response(checklist: Any) -> ChecklistResponse:
    """Build a ChecklistResponse from an ORM checklist."""
    return ChecklistResponse(
        id=checklist.id,
        system_id=checklist.system_id,
        kind=checklist.kind,
        title=checklist.title,
        description=checklist.description,
        created_by=checklist.created_by,
        metadata=getattr(checklist, "metadata_", {}),
        created_at=checklist.created_at,
        updated_at=checklist.updated_at,
    )


def _item_to_response(item: Any) -> ItemResponse:
    """Build an ItemResponse from an ORM checklist item."""
    return ItemResponse(
        id=item.id,
        checklist_id=item.checklist_id,
        sequence=item.sequence,
        description=item.description,
        status=item.status,
        result_note=item.result_note,
        verified_by=item.verified_by,
        verified_at=item.verified_at,
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _issue_to_response(issue: Any) -> IssueResponse:
    """Build an IssueResponse from an ORM issue."""
    return IssueResponse(
        id=issue.id,
        system_id=issue.system_id,
        description=issue.description,
        severity=issue.severity,
        status=issue.status,
        resolution=issue.resolution,
        raised_by=issue.raised_by,
        closed_by=issue.closed_by,
        closed_at=issue.closed_at,
        metadata=getattr(issue, "metadata_", {}),
        created_at=issue.created_at,
        updated_at=issue.updated_at,
    )


# -- Stats -------------------------------------------------------------------


@router.get("/stats", response_model=CxStatsResponse, dependencies=[_READ], include_in_schema=False)
@router.get("/stats/", response_model=CxStatsResponse, dependencies=[_READ])
async def cx_stats(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: CommissioningService = Depends(_get_service),
) -> CxStatsResponse:
    """Aggregate commissioning statistics for a project."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_stats(project_id)


# -- Systems -----------------------------------------------------------------


@router.get(
    "/systems",
    response_model=list[SystemResponse],
    dependencies=[_READ],
    include_in_schema=False,
)
@router.get("/systems/", response_model=list[SystemResponse], dependencies=[_READ])
async def list_systems(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    system_type: str | None = Query(default=None, alias="type"),
    service: CommissioningService = Depends(_get_service),
) -> list[SystemResponse]:
    """List commissionable systems for a project, each with its readiness."""
    await verify_project_access(project_id, user_id, session)
    systems, _ = await service.list_systems(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        system_type=system_type,
    )
    rmap = await service.readiness_map([s.id for s in systems])
    return [_system_to_response(s, rmap.get(s.id)) for s in systems]


@router.post("/systems/", response_model=SystemResponse, status_code=201, dependencies=[_WRITE])
async def create_system(
    data: SystemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> SystemResponse:
    """Create a new commissionable system."""
    await verify_project_access(data.project_id, user_id, session)
    try:
        system = await service.create_system(data, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        # Never echo ORM/DB internals to the client; log server-side with the
        # request-id and return a generic message plus the correlation id.
        from app.middleware.request_id import get_request_id

        request_id = get_request_id()
        logger.exception(
            "Cx create_system failed for project=%s (request_id=%s)",
            data.project_id,
            request_id or "-",
        )
        detail = "Failed to create system"
        if request_id:
            detail = f"{detail} (request_id: {request_id})"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail) from exc
    await session.commit()
    readiness = await service.readiness_summary(system.id)
    return _system_to_response(system, readiness)


@router.get("/systems/{system_id}", response_model=SystemResponse, dependencies=[_READ])
async def get_system(
    system_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> SystemResponse:
    """Get a single system with its live readiness breakdown."""
    system = await service.get_system(system_id)
    await verify_project_access(system.project_id, user_id, session)
    readiness = await service.readiness_summary(system_id)
    return _system_to_response(system, readiness)


@router.patch("/systems/{system_id}", response_model=SystemResponse, dependencies=[_WRITE])
async def update_system(
    system_id: uuid.UUID,
    data: SystemUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> SystemResponse:
    """Update a system's descriptive fields (not its commissioned state)."""
    existing = await service.get_system(system_id)
    await verify_project_access(existing.project_id, user_id, session)
    system = await service.update_system(system_id, data)
    await session.commit()
    readiness = await service.readiness_summary(system_id)
    return _system_to_response(system, readiness)


@router.delete("/systems/{system_id}", status_code=204, dependencies=[_WRITE])
async def delete_system(
    system_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> None:
    """Delete a system and all of its checklists, items and issues."""
    existing = await service.get_system(system_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_system(system_id)
    await session.commit()


@router.get(
    "/systems/{system_id}/readiness/",
    response_model=ReadinessSummary,
    dependencies=[_READ],
)
async def get_readiness(
    system_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> ReadinessSummary:
    """Return the explainable readiness breakdown for a system."""
    system = await service.get_system(system_id)
    await verify_project_access(system.project_id, user_id, session)
    readiness = await service.readiness_summary(system_id)
    return ReadinessSummary(**readiness)


@router.post(
    "/systems/{system_id}/commission/",
    response_model=SystemResponse,
    dependencies=[_COMMISSION],
)
async def commission_system(
    system_id: uuid.UUID,
    data: CommissionRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> SystemResponse:
    """Commission a system - blocked until every functional test passes and no critical issue is open."""
    system = await service.get_system(system_id)
    await verify_project_access(system.project_id, user_id, session)
    commissioned = await service.commission_system(system_id, data, user_id=user_id)
    await session.commit()
    readiness = await service.readiness_summary(system_id)
    return _system_to_response(commissioned, readiness)


# -- Checklists --------------------------------------------------------------


@router.get(
    "/systems/{system_id}/checklists/",
    response_model=list[ChecklistResponse],
    dependencies=[_READ],
)
async def list_checklists(
    system_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    kind: str | None = Query(default=None, alias="kind"),
    service: CommissioningService = Depends(_get_service),
) -> list[ChecklistResponse]:
    """List checklists for a system."""
    system = await service.get_system(system_id)
    await verify_project_access(system.project_id, user_id, session)
    checklists = await service.list_checklists(system_id, kind=kind)
    return [_checklist_to_response(c) for c in checklists]


@router.post(
    "/systems/{system_id}/checklists/",
    response_model=ChecklistResponse,
    status_code=201,
    dependencies=[_WRITE],
)
async def create_checklist(
    system_id: uuid.UUID,
    data: ChecklistCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> ChecklistResponse:
    """Create a checklist under a system."""
    system = await service.get_system(system_id)
    await verify_project_access(system.project_id, user_id, session)
    checklist = await service.create_checklist(system_id, data, user_id=user_id)
    await session.commit()
    return _checklist_to_response(checklist)


@router.patch("/checklists/{checklist_id}", response_model=ChecklistResponse, dependencies=[_WRITE])
async def update_checklist(
    checklist_id: uuid.UUID,
    data: ChecklistUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> ChecklistResponse:
    """Update a checklist."""
    _, system = await service.resolve_checklist_context(checklist_id)
    await verify_project_access(system.project_id, user_id, session)
    checklist = await service.update_checklist(checklist_id, data)
    await session.commit()
    return _checklist_to_response(checklist)


@router.delete("/checklists/{checklist_id}", status_code=204, dependencies=[_WRITE])
async def delete_checklist(
    checklist_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> None:
    """Delete a checklist and its items."""
    _, system = await service.resolve_checklist_context(checklist_id)
    await verify_project_access(system.project_id, user_id, session)
    await service.delete_checklist(checklist_id)
    await session.commit()


# -- Checklist items ---------------------------------------------------------


@router.get(
    "/checklists/{checklist_id}/items/",
    response_model=list[ItemResponse],
    dependencies=[_READ],
)
async def list_items(
    checklist_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> list[ItemResponse]:
    """List items for a checklist."""
    _, system = await service.resolve_checklist_context(checklist_id)
    await verify_project_access(system.project_id, user_id, session)
    items = await service.list_items(checklist_id)
    return [_item_to_response(i) for i in items]


@router.post(
    "/checklists/{checklist_id}/items/",
    response_model=ItemResponse,
    status_code=201,
    dependencies=[_WRITE],
)
async def create_item(
    checklist_id: uuid.UUID,
    data: ItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> ItemResponse:
    """Create an item under a checklist."""
    _, system = await service.resolve_checklist_context(checklist_id)
    await verify_project_access(system.project_id, user_id, session)
    item = await service.create_item(checklist_id, data, user_id=user_id)
    await session.commit()
    return _item_to_response(item)


@router.patch("/items/{item_id}", response_model=ItemResponse, dependencies=[_WRITE])
async def update_item(
    item_id: uuid.UUID,
    data: ItemUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> ItemResponse:
    """Update an item's description, order or status."""
    _, _, system = await service.resolve_item_context(item_id)
    await verify_project_access(system.project_id, user_id, session)
    item = await service.update_item(item_id, data)
    await session.commit()
    return _item_to_response(item)


@router.post("/items/{item_id}/result/", response_model=ItemResponse, dependencies=[_WRITE])
async def set_item_result(
    item_id: uuid.UUID,
    data: ItemResultRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> ItemResponse:
    """Record a pass / fail / na result against an item."""
    _, _, system = await service.resolve_item_context(item_id)
    await verify_project_access(system.project_id, user_id, session)
    item = await service.set_item_result(item_id, data, user_id=user_id)
    await session.commit()
    return _item_to_response(item)


@router.delete("/items/{item_id}", status_code=204, dependencies=[_WRITE])
async def delete_item(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> None:
    """Delete a checklist item."""
    _, _, system = await service.resolve_item_context(item_id)
    await verify_project_access(system.project_id, user_id, session)
    await service.delete_item(item_id)
    await session.commit()


# -- Issues ------------------------------------------------------------------


@router.get(
    "/systems/{system_id}/issues/",
    response_model=list[IssueResponse],
    dependencies=[_READ],
)
async def list_issues(
    system_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    status_filter: str | None = Query(default=None, alias="status"),
    service: CommissioningService = Depends(_get_service),
) -> list[IssueResponse]:
    """List issues for a system."""
    system = await service.get_system(system_id)
    await verify_project_access(system.project_id, user_id, session)
    issues = await service.list_issues(system_id, status_filter=status_filter)
    return [_issue_to_response(i) for i in issues]


@router.post(
    "/systems/{system_id}/issues/",
    response_model=IssueResponse,
    status_code=201,
    dependencies=[_WRITE],
)
async def create_issue(
    system_id: uuid.UUID,
    data: IssueCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> IssueResponse:
    """Raise an issue against a system."""
    system = await service.get_system(system_id)
    await verify_project_access(system.project_id, user_id, session)
    issue = await service.create_issue(system_id, data, user_id=user_id)
    await session.commit()
    return _issue_to_response(issue)


@router.patch("/issues/{issue_id}", response_model=IssueResponse, dependencies=[_WRITE])
async def update_issue(
    issue_id: uuid.UUID,
    data: IssueUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> IssueResponse:
    """Update an issue (change severity, close it with a resolution, ...)."""
    _, system = await service.resolve_issue_context(issue_id)
    await verify_project_access(system.project_id, user_id, session)
    issue = await service.update_issue(issue_id, data, user_id=user_id)
    await session.commit()
    return _issue_to_response(issue)


@router.delete("/issues/{issue_id}", status_code=204, dependencies=[_WRITE])
async def delete_issue(
    issue_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CommissioningService = Depends(_get_service),
) -> None:
    """Delete an issue."""
    _, system = await service.resolve_issue_context(issue_id)
    await verify_project_access(system.project_id, user_id, session)
    await service.delete_issue(issue_id)
    await session.commit()
