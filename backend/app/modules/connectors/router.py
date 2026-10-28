# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Connectors API routes (mounted at ``/api/v1/connectors`` by the loader).

* ``POST /sources/``              - register an inbound document source
* ``GET  /sources/``              - list a project's sources
* ``GET  /sources/{id}``          - fetch one source
* ``POST /sources/{id}/sync``     - scan the source and import new files

Registering and syncing a source read server-local paths, so they require an
admin role in addition to project access. Listing/reading a source only needs
project access.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequireRole, SessionDep, verify_project_access
from app.modules.connectors.schemas import (
    ConnectorSourceCreate,
    ConnectorSourceOut,
    SyncResultOut,
)
from app.modules.connectors.service import ConnectorService

router = APIRouter(tags=["connectors"])


@router.post(
    "/sources/",
    response_model=ConnectorSourceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireRole("admin"))],
)
async def create_source(
    payload: ConnectorSourceCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Project the source belongs to"),
) -> ConnectorSourceOut:
    """Register an inbound document source for a project (admin only)."""
    await verify_project_access(project_id, user_id, session)
    service = ConnectorService(session)
    try:
        source = await service.create_source(
            project_id=project_id,
            name=payload.name,
            root_path=payload.root_path,
            kind=payload.kind,
            enabled=payload.enabled,
            created_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ConnectorSourceOut.model_validate(source)


@router.get(
    "/sources/",
    response_model=list[ConnectorSourceOut],
)
async def list_sources(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Project to list sources for"),
) -> list[ConnectorSourceOut]:
    """List the registered connector sources for a project."""
    await verify_project_access(project_id, user_id, session)
    service = ConnectorService(session)
    sources = await service.list_sources(project_id)
    return [ConnectorSourceOut.model_validate(s) for s in sources]


@router.get(
    "/sources/{source_id}",
    response_model=ConnectorSourceOut,
)
async def get_source(
    source_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ConnectorSourceOut:
    """Fetch a single connector source (project access required)."""
    service = ConnectorService(session)
    source = await service.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector source not found")
    await verify_project_access(source.project_id, user_id, session)
    return ConnectorSourceOut.model_validate(source)


@router.post(
    "/sources/{source_id}/sync",
    response_model=SyncResultOut,
    dependencies=[Depends(RequireRole("admin"))],
)
async def sync_source(
    source_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SyncResultOut:
    """Scan the source's folder and import each new file as a document (admin only)."""
    service = ConnectorService(session)
    source = await service.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector source not found")
    await verify_project_access(source.project_id, user_id, session)
    result = await service.sync_source(source, user_id=user_id)
    return SyncResultOut(**result)
