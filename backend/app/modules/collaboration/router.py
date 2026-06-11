"""‌⁠‍Collaboration API routes.

Endpoints:
    GET    /comments              - List comments for entity (threaded)
    POST   /comments              - Create comment (with optional mentions + viewpoint)
    PATCH  /comments/{comment_id} - Edit comment text
    DELETE /comments/{comment_id} - Soft delete comment
    GET    /comments/{comment_id}/thread - Get full thread
    POST   /viewpoints            - Create standalone viewpoint
    GET    /viewpoints            - List viewpoints for entity
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.collaboration.schemas import (
    CommentCreate,
    CommentListResponse,
    CommentResponse,
    CommentUpdate,
    ViewpointCreate,
    ViewpointListResponse,
    ViewpointResponse,
)
from app.modules.collaboration.service import CollaborationService

router = APIRouter(tags=["collaboration"])
logger = logging.getLogger(__name__)


# Allowlist of entity types that can carry comments / viewpoints.
# This is the authoritative list - anything else is rejected at the
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
    """‌⁠‍Reject entity_type values that are not in the allowlist.

    Without this check the router persists comments against arbitrary
    entity_type strings (``"unicorn"``, ``"foo"``, etc.) which become
    orphaned metadata that nothing can clean up.
    """
    if entity_type not in _ALLOWED_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Unsupported entity_type '{entity_type}'. Allowed: {sorted(_ALLOWED_ENTITY_TYPES)}"),
        )


async def _resolve_entity_project_id(
    entity_type: str,
    entity_id: str,
    session: SessionDep,
) -> uuid.UUID | None:
    """Map a commentable entity to its owning project, when we can.

    Returns the project UUID for the entity types whose primary model carries
    a ``project_id`` (the high-traffic comment targets), or ``None`` for types
    we cannot map here yet. ``None`` is also returned when the id is malformed
    or the row does not exist - callers treat an unresolvable id as "no gate
    applied" rather than guessing.
    """
    try:
        eid = uuid.UUID(entity_id)
    except (ValueError, TypeError):
        return None
    try:
        from sqlalchemy import select

        if entity_type == "boq":
            from app.modules.boq.models import BOQ

            return (await session.execute(select(BOQ.project_id).where(BOQ.id == eid))).scalar_one_or_none()
        if entity_type == "boq_position":
            from app.modules.boq.models import BOQ, Position

            return (
                await session.execute(
                    select(BOQ.project_id).join(Position, Position.boq_id == BOQ.id).where(Position.id == eid)
                )
            ).scalar_one_or_none()
        if entity_type == "document":
            from app.modules.documents.models import Document

            return (await session.execute(select(Document.project_id).where(Document.id == eid))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - best-effort resolution, fall back to no gate
        logger.debug("collaboration entity resolve failed for %s/%s", entity_type, entity_id)
        return None
    return None


async def _verify_entity_access(
    entity_type: str,
    entity_id: str,
    user_id: str,
    session: SessionDep,
) -> None:
    """Verify the caller may read/write comments on the target entity.

    When the target IS a project, ``entity_id`` is the project UUID, so we
    gate on project membership exactly like every other single-resource
    handler (``verify_project_access`` -> 404 on missing OR denied, which
    avoids leaking UUID existence). For the high-traffic non-project targets
    (boq, boq_position, document) we resolve the owning project and gate on
    it, closing the cross-tenant read where any ``collaboration.read`` holder
    could enumerate another tenant's comments by entity id. Entity types we
    cannot yet map to a project (task, rfi, ncr, bim_*, ...) are left
    ungated here rather than guessed - tracked as residual.
    """
    if entity_type == "project":
        try:
            project_uuid = uuid.UUID(entity_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            ) from None
        await verify_project_access(project_uuid, str(user_id), session)
        return

    resolved = await _resolve_entity_project_id(entity_type, entity_id, session)
    if resolved is not None:
        await verify_project_access(resolved, str(user_id), session)


# ── Comments ─────────────────────────────────────────────────────────────


@router.get("/comments/", response_model=CommentListResponse)
async def list_comments(
    user_id: CurrentUserId,
    session: SessionDep,
    entity_type: str = Query(..., min_length=1, max_length=100),
    entity_id: str = Query(..., min_length=1, max_length=36),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("collaboration.read")),
    service: CollaborationService = Depends(_get_service),
) -> CommentListResponse:
    """‌⁠‍List top-level comments for an entity (replies loaded as nested)."""
    _validate_entity_type(entity_type)
    await _verify_entity_access(entity_type, entity_id, str(user_id), session)
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
    session: SessionDep,
    _perm: None = Depends(RequirePermission("collaboration.create")),
    service: CollaborationService = Depends(_get_service),
) -> CommentResponse:
    """Create a comment with optional @mentions and viewpoint."""
    _validate_entity_type(data.entity_type)
    await _verify_entity_access(data.entity_type, data.entity_id, str(user_id), session)
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
    """Edit a comment's text (author only - enforced by service)."""
    comment = await service.update_comment(comment_id, data, uuid.UUID(user_id))
    return CommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("collaboration.delete")),
    service: CollaborationService = Depends(_get_service),
) -> None:
    """Soft-delete a comment (author only - enforced by service)."""
    await service.delete_comment(comment_id, uuid.UUID(user_id))


@router.get("/comments/{comment_id}/thread/", response_model=list[CommentResponse])
async def get_thread(
    comment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("collaboration.read")),
    service: CollaborationService = Depends(_get_service),
) -> list[CommentResponse]:
    """Get the full thread starting from a comment."""
    # Gate on the root comment's entity before returning the thread - this
    # endpoint previously loaded purely by comment_id with no access check.
    root = await service.get_comment(comment_id)
    await _verify_entity_access(root.entity_type, root.entity_id, str(user_id), session)
    thread = await service.get_thread(comment_id)
    return [CommentResponse.model_validate(c) for c in thread]


# ── Viewpoints ───────────────────────────────────────────────────────────


@router.post("/viewpoints/", response_model=ViewpointResponse, status_code=201)
async def create_viewpoint(
    data: ViewpointCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("collaboration.create")),
    service: CollaborationService = Depends(_get_service),
) -> ViewpointResponse:
    """Create a standalone viewpoint (or linked to a comment)."""
    _validate_entity_type(data.entity_type)
    await _verify_entity_access(data.entity_type, data.entity_id, str(user_id), session)
    try:
        viewpoint = await service.create_viewpoint(data, uuid.UUID(user_id))
        return ViewpointResponse.model_validate(viewpoint)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create viewpoint")
        raise HTTPException(status_code=500, detail="Failed to create viewpoint")


@router.get("/viewpoints/", response_model=ViewpointListResponse)
async def list_viewpoints(
    user_id: CurrentUserId,
    session: SessionDep,
    entity_type: str = Query(..., min_length=1, max_length=100),
    entity_id: str = Query(..., min_length=1, max_length=36),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("collaboration.read")),
    service: CollaborationService = Depends(_get_service),
) -> ViewpointListResponse:
    """List viewpoints for an entity (paginated, mirrors list_comments)."""
    _validate_entity_type(entity_type)
    await _verify_entity_access(entity_type, entity_id, str(user_id), session)
    viewpoints, total = await service.list_viewpoints(
        entity_type,
        entity_id,
        offset=offset,
        limit=limit,
    )
    return ViewpointListResponse(
        items=[ViewpointResponse.model_validate(vp) for vp in viewpoints],
        total=total,
    )
