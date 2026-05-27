# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File tags API routes.

Mounted under ``/api/v1/file-tags/`` by the module loader:

    GET    /?project_id=&category=         List tags in a project.
    POST   /                               Create a tag.
    PATCH  /{id}/                          Rename / recolor.
    DELETE /{id}/                          Delete tag + cascades.
    POST   /{id}/assign/                   Bulk-assign to files.
    POST   /{id}/unassign/                 Bulk-unassign.
    GET    /by-file/?kind=&file_id=        Tags attached to one file.
    POST   /seed-defaults/?project_id=     Insert AECO standard tags.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.file_tags.schemas import (
    TagAssignmentRequest,
    TagAssignmentResponse,
    TagCreate,
    TagResponse,
    TagSeedResponse,
    TagUpdate,
)
from app.modules.file_tags.service import (
    assign_tag,
    create_tag,
    delete_tag,
    list_tags,
    seed_default_tags,
    tags_for_file,
    unassign_tag,
    update_tag,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _coerce_user_id(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None


@router.get(
    "/",
    response_model=list[TagResponse],
)
async def list_project_tags(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    category: str | None = Query(None),
    _: None = Depends(RequirePermission("file_tags.read")),
) -> list[TagResponse]:
    """List every tag in a project."""
    await verify_project_access(project_id, user_id, session)
    return await list_tags(session, project_id, category=category)


@router.post(
    "/",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_tag(
    payload: TagCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("file_tags.write")),
) -> TagResponse:
    """Create a new tag in the project."""
    await verify_project_access(payload.project_id, user_id, session)
    try:
        return await create_tag(session, payload, _coerce_user_id(user_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch(
    "/{tag_id}/",
    response_model=TagResponse,
)
async def update_project_tag(
    tag_id: uuid.UUID,
    payload: TagUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _: None = Depends(RequirePermission("file_tags.write")),
) -> TagResponse:
    """Rename / recolor / recategorize a tag."""
    await verify_project_access(project_id, user_id, session)
    result = await update_tag(session, project_id, tag_id, payload)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return result


@router.delete(
    "/{tag_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_tag(
    tag_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _: None = Depends(RequirePermission("file_tags.write")),
) -> None:
    """Delete a tag (cascades to every assignment)."""
    await verify_project_access(project_id, user_id, session)
    ok = await delete_tag(session, project_id, tag_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return


@router.post(
    "/{tag_id}/assign/",
    response_model=TagAssignmentResponse,
)
async def assign_tag_route(
    tag_id: uuid.UUID,
    payload: TagAssignmentRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _: None = Depends(RequirePermission("file_tags.assign")),
) -> TagAssignmentResponse:
    """Bulk-assign the tag to a list of files."""
    await verify_project_access(project_id, user_id, session)
    try:
        return await assign_tag(
            session,
            project_id,
            tag_id,
            payload.file_kind,
            payload.file_ids,
            _coerce_user_id(user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{tag_id}/unassign/",
    response_model=TagAssignmentResponse,
)
async def unassign_tag_route(
    tag_id: uuid.UUID,
    payload: TagAssignmentRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _: None = Depends(RequirePermission("file_tags.assign")),
) -> TagAssignmentResponse:
    """Bulk-unassign the tag from a list of files."""
    await verify_project_access(project_id, user_id, session)
    try:
        return await unassign_tag(
            session,
            project_id,
            tag_id,
            payload.file_kind,
            payload.file_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/by-file/",
    response_model=list[TagResponse],
)
async def list_tags_for_file(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    kind: str = Query(...),
    file_id: str = Query(...),
    _: None = Depends(RequirePermission("file_tags.read")),
) -> list[TagResponse]:
    """Return every tag attached to a single file."""
    await verify_project_access(project_id, user_id, session)
    return await tags_for_file(session, project_id, kind, file_id)


@router.post(
    "/seed-defaults/",
    response_model=TagSeedResponse,
)
async def seed_default_route(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _: None = Depends(RequirePermission("file_tags.write")),
) -> TagSeedResponse:
    """Insert the AECO standard tag set into the project (idempotent)."""
    await verify_project_access(project_id, user_id, session)
    return await seed_default_tags(session, project_id, _coerce_user_id(user_id))
