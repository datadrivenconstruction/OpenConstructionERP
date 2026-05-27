# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Versioning API routes.

Endpoints (auto-mounted at ``/api/v1/file-versions/``):

    GET    /                          — list versions for a file (chain)
    GET    /{version_id}/             — single version detail
    POST   /                          — register a new version
    POST   /{version_id}/restore/     — promote a historical version
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.file_versions.models import FILE_KINDS
from app.modules.file_versions.schemas import (
    FileVersionCreate,
    FileVersionResponse,
)
from app.modules.file_versions.service import FileVersionService

router = APIRouter()


def _get_service(session: SessionDep) -> FileVersionService:
    return FileVersionService(session)


def _to_response(row: object) -> FileVersionResponse:
    return FileVersionResponse.model_validate(row)


def _safe_user_uuid(user_id: str | None) -> uuid.UUID | None:
    if not user_id:
        return None
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None


@router.get(
    "/",
    response_model=list[FileVersionResponse],
    dependencies=[Depends(RequirePermission("file_versions.read"))],
)
async def list_versions(
    session: SessionDep,
    user_id: CurrentUserId,
    file_id: str = Query(..., min_length=1, max_length=64),
    kind: str = Query(..., alias="kind"),
    service: FileVersionService = Depends(_get_service),
) -> list[FileVersionResponse]:
    """List the version chain for a file, newest-first.

    Looks up the file's chain by row id; the service walks the chain
    via the matching ``(project_id, file_kind, canonical_name)`` so
    every historical row participates — not just rows that share the
    incoming ``file_id``.
    """
    if kind not in FILE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown kind: {kind!r}",
        )
    seeds = await service.list_for_file(file_id=file_id, file_kind=kind)
    if not seeds:
        return []
    seed = seeds[0]
    # Cross-project IDOR gate.
    await verify_project_access(seed.project_id, user_id, session)
    chain = await service.list_chain(
        project_id=seed.project_id,
        file_kind=seed.file_kind,
        canonical_name=seed.canonical_name,
    )
    return [_to_response(r) for r in chain]


@router.get(
    "/{version_id}/",
    response_model=FileVersionResponse,
    dependencies=[Depends(RequirePermission("file_versions.read"))],
)
async def get_version(
    version_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: FileVersionService = Depends(_get_service),
) -> FileVersionResponse:
    row = await service.get(version_id)
    await verify_project_access(row.project_id, user_id, session)
    return _to_response(row)


@router.post(
    "/",
    response_model=FileVersionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("file_versions.write"))],
)
async def create_version(
    payload: FileVersionCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    service: FileVersionService = Depends(_get_service),
) -> FileVersionResponse:
    """Register a new version row + supersede the prior current row."""
    await verify_project_access(payload.project_id, user_id, session)
    row = await service.register_new_version(payload, uploaded_by_id=_safe_user_uuid(user_id))
    return _to_response(row)


@router.post(
    "/{version_id}/restore/",
    response_model=FileVersionResponse,
    dependencies=[Depends(RequirePermission("file_versions.restore"))],
)
async def restore_version(
    version_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: FileVersionService = Depends(_get_service),
) -> FileVersionResponse:
    """Promote a historical version back to current.

    The currently-active row is demoted to superseded and chain pointers
    are rewritten so the timeline stays consistent.
    """
    target = await service.get(version_id)
    await verify_project_access(target.project_id, user_id, session)
    restored = await service.restore_version(version_id, actor_id=_safe_user_uuid(user_id))
    return _to_response(restored)
