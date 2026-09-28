# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Favourites API routes.

Mounted at ``/api/v1/file-favorites/`` (kebab-cased per the loader
convention). All endpoints are per-user - a caller can only see /
mutate their own favourite rows.

    GET    /                          - list current user's favourites
    POST   /                          - star (or pin) a file
    DELETE /                          - un-star (by kind+id, body or query)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.file_favorites.models import FAVORITE_KINDS
from app.modules.file_favorites.schemas import (
    FavoriteCreateRequest,
    FavoriteResponse,
)
from app.modules.file_favorites.service import (
    list_favorites,
    toggle_favorite,
    unstar,
)

router = APIRouter(tags=["file_favorites"])


def _user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier",
        ) from exc


@router.get(
    "/",
    response_model=list[FavoriteResponse],
    dependencies=[Depends(RequirePermission("file_favorites.read"))],
)
async def list_my_favorites(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(None),
    only_pinned: bool = Query(False),
) -> list[FavoriteResponse]:
    """Return the caller's favourites, pinned-first."""
    uid = _user_uuid(user_id)
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    rows = await list_favorites(
        session,
        user_id=uid,
        project_id=project_id,
        only_pinned=only_pinned,
    )
    return [FavoriteResponse.model_validate(r) for r in rows]


@router.post(
    "/",
    response_model=FavoriteResponse,
    dependencies=[Depends(RequirePermission("file_favorites.toggle"))],
)
async def star_file(
    payload: FavoriteCreateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    response: Response,
) -> FavoriteResponse:
    """Star (or update the pin flag of) a file for the caller.

    Idempotent on ``(user_id, file_kind, file_id)``: posting twice
    only flips the ``pinned`` flag, never duplicates the row. Returns
    201 on first insert, 200 on subsequent calls.
    """
    if payload.file_kind not in FAVORITE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown file_kind: {payload.file_kind!r}",
        )
    await verify_project_access(payload.project_id, user_id, session)
    uid = _user_uuid(user_id)
    row, created = await toggle_favorite(
        session,
        user_id=uid,
        project_id=payload.project_id,
        file_kind=payload.file_kind,
        file_id=payload.file_id,
        pinned=payload.pinned,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return FavoriteResponse.model_validate(row)


@router.delete(
    "/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("file_favorites.toggle"))],
)
async def unstar_file(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    file_kind: str = Query(..., min_length=1, max_length=32),
    file_id: str = Query(..., min_length=1, max_length=64),
) -> None:
    """Remove a favourite. Idempotent - missing rows return 204."""
    if file_kind not in FAVORITE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown file_kind: {file_kind!r}",
        )
    await verify_project_access(project_id, user_id, session)
    uid = _user_uuid(user_id)
    await unstar(
        session,
        user_id=uid,
        project_id=project_id,
        file_kind=file_kind,
        file_id=file_id,
    )
