# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Comments API routes.

Mounted by the module loader at ``/api/v1/file-comments/``.

    GET    /?kind=&file_id=&include_resolved=  Threaded list.
    POST   /                                   Create comment (extracts @mentions).
    PATCH  /{id}/                              Edit body / toggle resolved.
    DELETE /{id}/                              Soft delete (tombstone).
    GET    /mentions/me/                       Current user's unread inbox.
    POST   /mentions/{id}/acknowledge/         Mark a single mention notified.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.file_comments.schemas import (
    ALLOWED_FILE_KINDS,
    FileCommentCreate,
    FileCommentListResponse,
    FileCommentResponse,
    FileCommentUpdate,
    UnreadMentionListResponse,
)
from app.modules.file_comments.service import (
    acknowledge_mention,
    create_comment,
    list_threads,
    list_unread_mentions,
    soft_delete_comment,
    update_comment,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _coerce_user_uuid(user_id: str) -> uuid.UUID:
    """The JWT subject is a string — Pydantic schemas need a UUID."""
    try:
        return uuid.UUID(user_id)
    except (ValueError, TypeError) as exc:
        # A non-UUID subject means the token was issued for a service
        # account that has no presence in oe_users_user; the comment
        # author_id FK would fail anyway.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a user UUID",
        ) from exc


def _validate_kind(kind: str) -> None:
    if kind not in ALLOWED_FILE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown file_kind: {kind!r}",
        )


# ── Threads ────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=FileCommentListResponse,
)
async def list_file_threads(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: Annotated[uuid.UUID, Query(...)],
    kind: Annotated[str, Query(...)],
    file_id: Annotated[str, Query(..., min_length=1, max_length=255)],
    include_resolved: Annotated[bool, Query()] = False,
    _: None = Depends(RequirePermission("file_comments.read")),
) -> FileCommentListResponse:
    """List threaded comments on a file."""
    _validate_kind(kind)
    await verify_project_access(project_id, user_id, session)
    threads, total = await list_threads(
        session,
        project_id=project_id,
        file_kind=kind,
        file_id=file_id,
        include_resolved=include_resolved,
    )
    return FileCommentListResponse(
        file_kind=kind,
        file_id=file_id,
        threads=threads,
        total=total,
    )


@router.post(
    "/",
    response_model=FileCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_file_comment(
    payload: FileCommentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("file_comments.write")),
) -> FileCommentResponse:
    """Create a top-level comment or a reply (when ``parent_id`` is set)."""
    await verify_project_access(payload.project_id, user_id, session)
    author_uuid = _coerce_user_uuid(user_id)
    try:
        comment, mentions = await create_comment(session, payload, author_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return FileCommentResponse(
        id=comment.id,
        project_id=comment.project_id,
        file_kind=comment.file_kind,
        file_id=comment.file_id,
        file_version_snapshot=comment.file_version_snapshot,
        parent_id=comment.parent_id,
        author_id=comment.author_id,
        body=comment.body,
        page_number=comment.page_number,
        anchor_x=comment.anchor_x,
        anchor_y=comment.anchor_y,
        resolved=comment.resolved,
        resolved_at=comment.resolved_at,  # type: ignore[arg-type]
        resolved_by_id=comment.resolved_by_id,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        mentions=[
            # ``from_attributes=True`` would re-fetch each row; ORM is
            # already loaded, so map by hand to keep this hot path tight.
            {
                "id": m.id,
                "comment_id": m.comment_id,
                "mentioned_user_id": m.mentioned_user_id,
                "notified_at": m.notified_at,
                "created_at": m.created_at,
            }  # type: ignore[list-item]
            for m in mentions
        ],
    )


@router.patch(
    "/{comment_id}/",
    response_model=FileCommentResponse,
)
async def patch_file_comment(
    comment_id: uuid.UUID,
    payload: FileCommentUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _w: None = Depends(RequirePermission("file_comments.write")),
    # The ``resolve`` permission gate runs only when the request toggles
    # the resolved flag — see below.
) -> FileCommentResponse:
    """Edit body and/or toggle resolved.

    If the request toggles the resolved flag, the caller must also hold
    ``file_comments.resolve``. We don't put the resolve permission on
    the decorator (it would block plain body edits for users who can
    only write); the gate is evaluated inline.
    """
    # Inline resolve-gate
    if payload.resolved is not None:
        from app.core.permissions import permission_registry
        from app.modules.users.repository import UserRepository

        repo = UserRepository(session)
        user = await repo.get_by_id(_coerce_user_uuid(user_id))
        role = getattr(user, "role", "") if user is not None else ""
        if role != "admin" and not permission_registry.role_has_permission(role, "file_comments.resolve"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission: file_comments.resolve",
            )

    actor_uuid = _coerce_user_uuid(user_id)
    try:
        result = await update_comment(session, comment_id, payload, actor_uuid)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    comment, mentions = result

    # Author boundary + project access guard — even though the body /
    # resolve gates run above, a stranger should not be able to mutate
    # a comment in a project they cannot see.
    await verify_project_access(comment.project_id, user_id, session)

    return FileCommentResponse(
        id=comment.id,
        project_id=comment.project_id,
        file_kind=comment.file_kind,
        file_id=comment.file_id,
        file_version_snapshot=comment.file_version_snapshot,
        parent_id=comment.parent_id,
        author_id=comment.author_id,
        body=comment.body,
        page_number=comment.page_number,
        anchor_x=comment.anchor_x,
        anchor_y=comment.anchor_y,
        resolved=comment.resolved,
        resolved_at=comment.resolved_at,  # type: ignore[arg-type]
        resolved_by_id=comment.resolved_by_id,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        mentions=[
            {
                "id": m.id,
                "comment_id": m.comment_id,
                "mentioned_user_id": m.mentioned_user_id,
                "notified_at": m.notified_at,
                "created_at": m.created_at,
            }  # type: ignore[list-item]
            for m in mentions
        ],
    )


@router.delete(
    "/{comment_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file_comment(
    comment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("file_comments.write")),
) -> None:
    """Soft-delete a comment (body replaced with ``[deleted]``)."""
    actor_uuid = _coerce_user_uuid(user_id)
    try:
        ok = await soft_delete_comment(session, comment_id, actor_uuid)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return


# ── Mentions inbox ─────────────────────────────────────────────────────


@router.get(
    "/mentions/me/",
    response_model=UnreadMentionListResponse,
)
async def list_my_unread_mentions(
    session: SessionDep,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _: None = Depends(RequirePermission("file_comments.read")),
) -> UnreadMentionListResponse:
    """Return the calling user's unread @mentions."""
    me = _coerce_user_uuid(user_id)
    items, total = await list_unread_mentions(session, me, limit=limit)
    return UnreadMentionListResponse(items=items, total=total)


@router.post(
    "/mentions/{mention_id}/acknowledge/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def acknowledge_my_mention(
    mention_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("file_comments.read")),
) -> None:
    """Mark a mention as notified so it leaves the unread inbox."""
    me = _coerce_user_uuid(user_id)
    ok = await acknowledge_mention(session, mention_id, me)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mention not found",
        )
    return
