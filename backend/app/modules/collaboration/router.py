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

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
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


# Allowlist of entity types that can carry comments / viewpoints.
# This is the authoritative list — anything else is rejected at the
# router boundary so we never persist orphaned references.  Adding a
# new entity type to this set is a deliberate, reviewed change.
_ALLOWED_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "project",
        "boq",
        "boq_position",
        "document",
        "task",
        "schedule_activity",
        "bim_model",
        "bim_element",
        "requirement",
        "rfi",
        "submittal",
        "ncr",
        "punchlist_item",
        "inspection",
        "meeting",
        "transmittal",
        "bcf_topic",
    }
)


def _get_service(session: SessionDep) -> CollaborationService:
    return CollaborationService(session)


def _validate_entity_type(entity_type: str) -> None:
    """Reject entity_type values that are not in the allowlist.

    Without this check the router persists comments against arbitrary
    entity_type strings (``"unicorn"``, ``"foo"``, etc.) which become
    orphaned metadata that nothing can clean up.
    """
    if entity_type not in _ALLOWED_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported entity_type '{entity_type}'. "
                f"Allowed: {sorted(_ALLOWED_ENTITY_TYPES)}"
            ),
        )


# ── Comments ─────────────────────────────────────────────────────────────


@router.get("/comments/", response_model=CommentListResponse)
async def list_comments(
    _user_id: CurrentUserId,
    entity_type: str = Query(..., min_length=1, max_length=100),
    entity_id: str = Query(..., min_length=1, max_length=36),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("collaboration.read")),
    service: CollaborationService = Depends(_get_service),
) -> CommentListResponse:
    """List top-level comments for an entity (replies loaded as nested)."""
    _validate_entity_type(entity_type)
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
    _perm: None = Depends(RequirePermission("collaboration.create")),
    service: CollaborationService = Depends(_get_service),
) -> CommentResponse:
    """Create a comment with optional @mentions and viewpoint."""
    _validate_entity_type(data.entity_type)
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
    _perm: None = Depends(RequirePermission("collaboration.update")),
    service: CollaborationService = Depends(_get_service),
) -> CommentResponse:
    """Edit a comment's text (author only — enforced by service)."""
    comment = await service.update_comment(comment_id, data, uuid.UUID(user_id))
    return CommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("collaboration.delete")),
    service: CollaborationService = Depends(_get_service),
) -> None:
    """Soft-delete a comment (author only — enforced by service)."""
    await service.delete_comment(comment_id, uuid.UUID(user_id))


@router.get("/comments/{comment_id}/thread/", response_model=list[CommentResponse])
async def get_thread(
    comment_id: uuid.UUID,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("collaboration.read")),
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
    _perm: None = Depends(RequirePermission("collaboration.create")),
    service: CollaborationService = Depends(_get_service),
) -> ViewpointResponse:
    """Create a standalone viewpoint (or linked to a comment)."""
    _validate_entity_type(data.entity_type)
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
    _user_id: CurrentUserId,
    entity_type: str = Query(..., min_length=1, max_length=100),
    entity_id: str = Query(..., min_length=1, max_length=36),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("collaboration.read")),
    service: CollaborationService = Depends(_get_service),
) -> list[ViewpointResponse]:
    """List viewpoints for an entity."""
    _validate_entity_type(entity_type)
    viewpoints, _ = await service.list_viewpoints(
        entity_type,
        entity_id,
        offset=offset,
        limit=limit,
    )
    return [ViewpointResponse.model_validate(vp) for vp in viewpoints]
