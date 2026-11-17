# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue API routes (mounted at ``/api/v1/project-catalogue``).

Endpoints:
    GET    /projects/{project_id}/items              - the project's rates with status against source
    POST   /projects/{project_id}/items              - add a rate of the project's own
    POST   /projects/{project_id}/items/import       - copy rows of the cost database or resource catalogue
    POST   /projects/{project_id}/items/sync         - take the moved source price, or keep the local one
    GET    /projects/{project_id}/sources            - search what can be copied in
    POST   /projects/{project_id}/validate           - the ``project_catalogue`` rule set
    PATCH  /items/{item_id}                          - edit a project rate (the source is never written)
    DELETE /items/{item_id}                          - remove a project rate
    GET    /items/{item_id}/positions                - bill lines this rate can price
    POST   /items/{item_id}/apply                    - price bill lines from this rate
    POST   /items/{item_id}/push                     - re-price the bill lines this rate priced
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.project_catalogue.models import ProjectCatalogueItem
from app.modules.project_catalogue.schemas import (
    ApplyRequest,
    ApplyResult,
    CandidateListResponse,
    ImportRequest,
    ImportResult,
    ItemCreate,
    ItemListResponse,
    ItemResponse,
    ItemUpdate,
    SourceSearchResponse,
    SyncRequest,
    SyncResult,
    ValidationReportOut,
)
from app.modules.project_catalogue.service import ProjectCatalogueService, not_found

router = APIRouter(tags=["project_catalogue"])

_READ = [Depends(RequirePermission("project_catalogue.read"))]
_WRITE = [Depends(RequirePermission("project_catalogue.write"))]

_STATUS_PATTERN = "^(|in_sync|overridden|source_changed|source_missing|manual)$"


def _actor(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None


async def _owned_item(service: ProjectCatalogueService, item_id: uuid.UUID, user_id: str) -> ProjectCatalogueItem:
    item = await service.get_item(item_id)
    if item is None:
        raise not_found()
    await verify_project_access(item.project_id, user_id, service.session)
    return item


@router.get("/projects/{project_id}/items", response_model=ItemListResponse, dependencies=_READ)
async def list_items(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status_filter: str = Query("", alias="status", pattern=_STATUS_PATTERN),
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> ItemListResponse:
    """The project's rates, each with where it stands against its source."""
    await verify_project_access(project_id, user_id, session)
    return await ProjectCatalogueService(session).list_items(
        project_id, status_filter=status_filter, q=q.strip(), offset=offset, limit=limit
    )


@router.post(
    "/projects/{project_id}/items",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_item(
    project_id: uuid.UUID, data: ItemCreate, session: SessionDep, user_id: CurrentUserId
) -> ItemResponse:
    """Add a rate that exists only in this project."""
    await verify_project_access(project_id, user_id, session)
    service = ProjectCatalogueService(session)
    item, warnings = await service.create_manual(project_id, data, _actor(user_id))
    return await service.item_response(item, warnings)


@router.post("/projects/{project_id}/items/import", response_model=ImportResult, dependencies=_WRITE)
async def import_items(
    project_id: uuid.UUID, data: ImportRequest, session: SessionDep, user_id: CurrentUserId
) -> ImportResult:
    """Copy source rows into the project; rows already copied are skipped."""
    await verify_project_access(project_id, user_id, session)
    return await ProjectCatalogueService(session).import_from_source(
        project_id, data.source_type, data.source_ids, _actor(user_id)
    )


@router.post("/projects/{project_id}/items/sync", response_model=SyncResult, dependencies=_WRITE)
async def sync_items(
    project_id: uuid.UUID, data: SyncRequest, session: SessionDep, user_id: CurrentUserId
) -> SyncResult:
    """Take the source's current price, or keep the local rate and acknowledge the new source price."""
    await verify_project_access(project_id, user_id, session)
    return await ProjectCatalogueService(session).sync(project_id, data.action, data.item_ids)


@router.get("/projects/{project_id}/sources", response_model=SourceSearchResponse, dependencies=_READ)
async def search_sources(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    source_type: str = Query("cost_item", pattern="^(cost_item|catalog_resource)$"),
    q: str = Query("", max_length=200),
    region: str = Query("", max_length=50),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
) -> SourceSearchResponse:
    """Search the cost database or the resource catalogue for rows to copy in."""
    await verify_project_access(project_id, user_id, session)
    return await ProjectCatalogueService(session).search_sources(
        project_id, source_type, q.strip(), region.strip(), offset, limit
    )


@router.post("/projects/{project_id}/validate", response_model=ValidationReportOut, dependencies=_READ)
async def validate_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ValidationReportOut:
    """Run the project catalogue rules over the whole catalogue."""
    from app.core.i18n import get_locale  # noqa: PLC0415

    await verify_project_access(project_id, user_id, session)
    return await ProjectCatalogueService(session).validate(project_id, locale=get_locale())


@router.patch("/items/{item_id}", response_model=ItemResponse, dependencies=_WRITE)
async def update_item(
    item_id: uuid.UUID, data: ItemUpdate, session: SessionDep, user_id: CurrentUserId
) -> ItemResponse:
    """Edit a project rate. The cost database and company library stay as they are."""
    service = ProjectCatalogueService(session)
    item = await _owned_item(service, item_id, user_id)
    warnings = await service.update_item(item, data)
    return await service.item_response(item, warnings)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_item(item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> None:
    """Remove a project rate. Bill lines it priced keep their price."""
    service = ProjectCatalogueService(session)
    await service.delete_item(await _owned_item(service, item_id, user_id))


@router.get("/items/{item_id}/positions", response_model=CandidateListResponse, dependencies=_READ)
async def position_candidates(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    q: str = Query("", max_length=200),
    same_unit: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> CandidateListResponse:
    """Bill lines of the project this rate can price, same unit first by default."""
    service = ProjectCatalogueService(session)
    item = await _owned_item(service, item_id, user_id)
    return await service.position_candidates(item, q.strip(), same_unit, offset, limit)


@router.post("/items/{item_id}/apply", response_model=ApplyResult, dependencies=_WRITE)
async def apply_item(
    item_id: uuid.UUID, data: ApplyRequest, session: SessionDep, user_id: CurrentUserId
) -> ApplyResult:
    """Price the chosen bill lines from this rate and remember the link."""
    service = ProjectCatalogueService(session)
    item = await _owned_item(service, item_id, user_id)
    return await service.apply_to_positions(item, data.position_ids, _actor(user_id))


@router.post("/items/{item_id}/push", response_model=ApplyResult, dependencies=_WRITE)
async def push_item(item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ApplyResult:
    """Bring every bill line this rate priced up to its current rate."""
    service = ProjectCatalogueService(session)
    item = await _owned_item(service, item_id, user_id)
    return await service.push_to_linked(item, _actor(user_id))
