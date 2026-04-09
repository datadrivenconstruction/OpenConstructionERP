"""Collaboration API routes.

Endpoints:
    GET    /comments              — List comments for entity (threaded)
    POST   /comments              — Create comment (with optional mentions + viewpoint)
    PATCH  /comments/{comment_id} — Edit comment text
    DELETE /comments/{comment_id} — Soft delete comment
    GET    /comments/{comment_id}/thread — Get full thread
    POST   /viewpoints            — Create standalone viewpoint
    GET    /viewpoints            — List viewpoints for entity
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.collaboration.schemas import (
    CommentCreate,
    CommentListResponse,
    CommentResponse,
    CommentUpdate,
    ViewpointCreate,
    ViewpointResponse,
)
from app.modules.collaboration.service import CollaborationService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> CollaborationService:
    return CollaborationService(session)


# ── Comments ─────────────────────────────────────────────────────────────


@router.get("/comments/", response_model=CommentListResponse)
async def list_comments(
    entity_type: str = Query(..., min_length=1, max_length=100),
    entity_id: str = Query(..., min_length=1, max_length=36),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: CollaborationService = Depends(_get_service),
) -> CommentListResponse:
    """List top-level comments for an entity (replies loaded as nested)."""
    comments, total = await service.list_comments(
        entity_type,
        entity_id,
        offset=offset,
        limit=limit,
    )
    return CommentListResponse(
        items=[CommentResponse.model_validate(c) for c in comments],
        total=total,
    )


@router.post("/comments/", response_model=CommentResponse, status_code=201)
async def create_comment(
    data: CommentCreate,
    user_id: CurrentUserId,
    service: CollaborationService = Depends(_get_service),
) -> CommentResponse:
    """Create a comment with optional @mentions and viewpoint."""
    try:
        comment = await service.create_comment(data, uuid.UUID(user_id))
        return CommentResponse.model_validate(comment)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create comment")
        raise HTTPException(status_code=500, detail="Failed to create comment")


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: uuid.UUID,
    data: CommentUpdate,
    user_id: CurrentUserId,
    service: CollaborationService = Depends(_get_service),
) -> CommentResponse:
    """Edit a comment's text (author only)."""
    comment = await service.update_comment(comment_id, data, uuid.UUID(user_id))
    return CommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    user_id: CurrentUserId,
    service: CollaborationService = Depends(_get_service),
) -> None:
    """Soft-delete a comment (author only)."""
    await service.delete_comment(comment_id, uuid.UUID(user_id))


@router.get("/comments/{comment_id}/thread/", response_model=list[CommentResponse])
async def get_thread(
    comment_id: uuid.UUID,
    service: CollaborationService = Depends(_get_service),
) -> list[CommentResponse]:
    """Get the full thread starting from a comment."""
    thread = await service.get_thread(comment_id)
    return [CommentResponse.model_validate(c) for c in thread]


# ── Viewpoints ───────────────────────────────────────────────────────────


@router.post("/viewpoints/", response_model=ViewpointResponse, status_code=201)
async def create_viewpoint(
    data: ViewpointCreate,
    user_id: CurrentUserId,
    service: CollaborationService = Depends(_get_service),
) -> ViewpointResponse:
    """Create a standalone viewpoint (or linked to a comment)."""
    try:
        viewpoint = await service.create_viewpoint(data, uuid.UUID(user_id))
        return ViewpointResponse.model_validate(viewpoint)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create viewpoint")
        raise HTTPException(status_code=500, detail="Failed to create viewpoint")


@router.get("/viewpoints/", response_model=list[ViewpointResponse])
async def list_viewpoints(
    entity_type: str = Query(..., min_length=1, max_length=100),
    entity_id: str = Query(..., min_length=1, max_length=36),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: CollaborationService = Depends(_get_service),
) -> list[ViewpointResponse]:
    """List viewpoints for an entity."""
    viewpoints, _ = await service.list_viewpoints(
        entity_type,
        entity_id,
        offset=offset,
        limit=limit,
    )
    return [ViewpointResponse.model_validate(vp) for vp in viewpoints]
