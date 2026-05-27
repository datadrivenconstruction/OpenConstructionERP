# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP routes for the file-saved-views module.

Mounted by the module loader at ``/api/v1/file-saved-views``.

Endpoints:
    GET    /                   — list views for ``project_id`` (or
                                 NULL = global) visible to the caller
    POST   /                   — create a view from the current filter
    PATCH  /{id}/              — rename / repin / reorder / re-snap
    DELETE /{id}/              — delete (owner only)
    POST   /{id}/use/          — bump use_count + last_used_at
    POST   /{id}/duplicate/    — clone into the caller's own list
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.file_saved_views.schemas import (
    SavedViewCreate,
    SavedViewListResponse,
    SavedViewResponse,
    SavedViewUpdate,
)
from app.modules.file_saved_views.service import (
    SavedViewConflictError,
    SavedViewNotFoundError,
    SavedViewService,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_response(view, *, current_user_id: uuid.UUID) -> SavedViewResponse:
    """Wrap an ORM row in the response schema, marking ownership."""
    return SavedViewResponse(
        id=view.id,
        user_id=view.user_id,
        project_id=view.project_id,
        name=view.name,
        icon=view.icon,
        filter_json=view.filter_json or {},
        sort_order=view.sort_order,
        is_pinned=view.is_pinned,
        is_shared=view.is_shared,
        last_used_at=view.last_used_at,
        use_count=view.use_count,
        created_at=view.created_at,
        updated_at=view.updated_at,
        is_own=view.user_id == current_user_id,
    )


def _user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier",
        ) from exc


# ── List ─────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=SavedViewListResponse,
    summary="List saved views visible to the caller",
    dependencies=[Depends(RequirePermission("file_saved_views.read"))],
)
async def list_saved_views(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(
        default=None,
        description=("Project to scope to. Omit for the user's global views (`project_id IS NULL`)."),
    ),
) -> SavedViewListResponse:
    user_uuid = _user_uuid(current_user_id)
    service = SavedViewService(session)
    rows = await service.list_views(user_id=user_uuid, project_id=project_id)
    return SavedViewListResponse(
        items=[_to_response(v, current_user_id=user_uuid) for v in rows],
        total=len(rows),
    )


# ── Create ───────────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=SavedViewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a saved view from the current filter snapshot",
    dependencies=[Depends(RequirePermission("file_saved_views.write"))],
)
async def create_saved_view(
    payload: SavedViewCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> SavedViewResponse:
    user_uuid = _user_uuid(current_user_id)
    service = SavedViewService(session)
    try:
        view = await service.create(payload, user_uuid)
    except SavedViewConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A view named {payload.name!r} already exists",
        ) from exc
    return _to_response(view, current_user_id=user_uuid)


# ── Patch ────────────────────────────────────────────────────────────────────


@router.patch(
    "/{view_id}/",
    response_model=SavedViewResponse,
    summary="Update a saved view (owner only)",
    dependencies=[Depends(RequirePermission("file_saved_views.write"))],
)
async def update_saved_view(
    view_id: uuid.UUID,
    payload: SavedViewUpdate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> SavedViewResponse:
    user_uuid = _user_uuid(current_user_id)
    service = SavedViewService(session)
    try:
        view = await service.update(view_id, payload, user_uuid)
    except SavedViewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved view not found",
        ) from exc
    except SavedViewConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A view with that name already exists",
        ) from exc
    return _to_response(view, current_user_id=user_uuid)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete(
    "/{view_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved view (owner only)",
    dependencies=[Depends(RequirePermission("file_saved_views.write"))],
)
async def delete_saved_view(
    view_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    user_uuid = _user_uuid(current_user_id)
    service = SavedViewService(session)
    try:
        await service.delete(view_id, user_uuid)
    except SavedViewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved view not found",
        ) from exc


# ── Use ──────────────────────────────────────────────────────────────────────


@router.post(
    "/{view_id}/use/",
    response_model=SavedViewResponse,
    summary="Mark a saved view as applied (bumps use_count + last_used_at)",
    dependencies=[Depends(RequirePermission("file_saved_views.read"))],
)
async def use_saved_view(
    view_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> SavedViewResponse:
    user_uuid = _user_uuid(current_user_id)
    service = SavedViewService(session)
    try:
        view = await service.use(view_id, user_uuid)
    except SavedViewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved view not found",
        ) from exc
    return _to_response(view, current_user_id=user_uuid)


# ── Duplicate ────────────────────────────────────────────────────────────────


@router.post(
    "/{view_id}/duplicate/",
    response_model=SavedViewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate a saved view into the caller's list",
    dependencies=[Depends(RequirePermission("file_saved_views.write"))],
)
async def duplicate_saved_view(
    view_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> SavedViewResponse:
    user_uuid = _user_uuid(current_user_id)
    service = SavedViewService(session)
    try:
        clone = await service.duplicate(view_id, user_uuid)
    except SavedViewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved view not found",
        ) from exc
    return _to_response(clone, current_user_id=user_uuid)
