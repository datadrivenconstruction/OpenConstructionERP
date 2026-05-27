# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Trash API routes (auto-mounted at /api/v1/file-trash/).

Endpoints:

    GET    /?project_id=...           — list trash rows for a project
    POST   /                          — soft-delete a file
    GET    /stats/?project_id=...     — count + bytes in trash
    POST   /{id}/restore/             — restore a trashed file
    DELETE /{id}                      — hard-purge a trashed file
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.file_trash.schemas import (
    TrashItemResponse,
    TrashListResponse,
    TrashPurgeRequest,
    TrashRestoreRequest,
    TrashSoftDeleteRequest,
    TrashStatsResponse,
)
from app.modules.file_trash.service import FileTrashService, purge_expired_trash

router = APIRouter()


def _get_service(session: SessionDep) -> FileTrashService:
    return FileTrashService(session)


def _to_response(row: object) -> TrashItemResponse:
    return TrashItemResponse.model_validate(row)


def _safe_user_uuid(user_id: str | None) -> uuid.UUID | None:
    if not user_id:
        return None
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None


@router.get(
    "/",
    response_model=TrashListResponse,
    dependencies=[Depends(RequirePermission("file_trash.read"))],
)
async def list_trash(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    service: FileTrashService = Depends(_get_service),
) -> TrashListResponse:
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.list_for_project(project_id, offset=offset, limit=limit)
    return TrashListResponse(
        items=[_to_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stats/",
    response_model=TrashStatsResponse,
    dependencies=[Depends(RequirePermission("file_trash.read"))],
)
async def trash_stats(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    service: FileTrashService = Depends(_get_service),
) -> TrashStatsResponse:
    await verify_project_access(project_id, user_id, session)
    count, rows, oldest, newest = await service.repo.stats_for_project(project_id)
    total_bytes = sum(r.file_size for r in rows)
    return TrashStatsResponse(
        project_id=project_id,
        count=count,
        total_bytes=total_bytes,
        oldest_trashed_at=oldest,
        newest_trashed_at=newest,
    )


@router.post(
    "/",
    response_model=TrashItemResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("file_trash.write"))],
)
async def soft_delete(
    payload: TrashSoftDeleteRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    service: FileTrashService = Depends(_get_service),
) -> TrashItemResponse:
    await verify_project_access(payload.project_id, user_id, session)
    row = await service.soft_delete(
        project_id=payload.project_id,
        kind=payload.kind,
        original_id=payload.original_id,
        canonical_name=payload.canonical_name,
        payload=payload.payload,
        retention_days=payload.retention_days,
        actor_id=_safe_user_uuid(user_id),
    )
    return _to_response(row)


@router.post(
    "/{trash_id}/restore/",
    response_model=TrashItemResponse,
    dependencies=[Depends(RequirePermission("file_trash.restore"))],
)
async def restore_trash(
    trash_id: uuid.UUID,
    _body: TrashRestoreRequest | None,
    session: SessionDep,
    user_id: CurrentUserId,
    service: FileTrashService = Depends(_get_service),
) -> TrashItemResponse:
    row = await service.get(trash_id)
    await verify_project_access(row.project_id, user_id, session)
    restored = await service.restore(trash_id, actor_id=_safe_user_uuid(user_id))
    return _to_response(restored)


@router.delete(
    "/{trash_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("file_trash.purge"))],
)
async def purge_trash(
    trash_id: uuid.UUID,
    body: TrashPurgeRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    service: FileTrashService = Depends(_get_service),
) -> None:
    row = await service.get(trash_id)
    await verify_project_access(row.project_id, user_id, session)
    await service.purge(trash_id, confirm_token=body.confirm_token)


@router.post(
    "/purge-now",
    dependencies=[Depends(RequirePermission("file_trash.purge"))],
)
async def purge_now(
    session: SessionDep,
    user_id: CurrentUserId,  # noqa: ARG001 — gate by permission, not by user
) -> dict[str, int]:
    """Admin trigger for the retention purge job.

    Walks ``oe_file_trash`` and hard-deletes every row whose
    ``trashed_at + retention_days`` window has lapsed. Designed for
    manual smoke testing — the same function runs on a 24-hour
    scheduler from :func:`app.modules.file_trash.jobs.register_jobs`.
    """
    purged = await purge_expired_trash(session)
    await session.commit()
    return {"purged": purged}
