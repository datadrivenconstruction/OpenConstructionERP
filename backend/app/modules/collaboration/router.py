# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Collaboration API routes.

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


# Records of modules built with the module builder take comments as
# ``built.<key>`` when their spec turns comments on. Those modules are
# installed at runtime, so they cannot be listed above: the shape is accepted
# here and everything else is decided per request by
# :func:`_resolve_built_project_id`, which fails closed for a key that is not
# a loaded built module with comments on.
_BUILT_PREFIX = "built."


def _built_key(entity_type: str) -> str | None:
    """The module key of a ``built.<key>`` entity type, or None for any other."""
    if not entity_type.startswith(_BUILT_PREFIX):
        return None
    from app.modules.module_builder.spec import IDENTIFIER_RE

    key = entity_type[len(_BUILT_PREFIX) :]
    return key if IDENTIFIER_RE.match(key) else None


def _get_service(session: SessionDep) -> CollaborationService:
    return CollaborationService(session)


def _validate_entity_type(entity_type: str) -> None:
    """Reject entity_type values that are not in the allowlist.

    Without this check the router persists comments against arbitrary
    entity_type strings (``"unicorn"``, ``"foo"``, etc.) which become
    orphaned metadata that nothing can clean up.
    """
    if entity_type not in _ALLOWED_ENTITY_TYPES and _built_key(entity_type) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Unsupported entity_type '{entity_type}'. Allowed: {sorted(_ALLOWED_ENTITY_TYPES)}"),
        )


async def _resolve_entity_project_id(
    entity_type: str,
    entity_id: str,
    session: SessionDep,
) -> uuid.UUID | None:
    """Map a commentable entity to its owning project.

    Returns the project UUID for every allow-listed entity type whose primary
    model can be traced to a ``project_id`` (directly or through one FK hop).
    Returns ``None`` only when the id is malformed, the row does not exist, or
    the type genuinely cannot be mapped to a project. Callers treat ``None``
    as fail-closed (access denied), so no allow-listed type is silently
    ungated.
    """
    try:
        eid = uuid.UUID(entity_id)
    except (ValueError, TypeError):
        return None
    try:
        from sqlalchemy import select

        # ── A record of a module built with the module builder ──────────
        built_key = _built_key(entity_type)
        if built_key is not None:
            return await _resolve_built_project_id(built_key, eid, session)

        # ── Direct project_id on the primary model ──────────────────────
        if entity_type == "boq":
            from app.modules.boq.models import BOQ

            return (await session.execute(select(BOQ.project_id).where(BOQ.id == eid))).scalar_one_or_none()
        if entity_type == "document":
            from app.modules.documents.models import Document

            return (await session.execute(select(Document.project_id).where(Document.id == eid))).scalar_one_or_none()
        if entity_type == "task":
            from app.modules.tasks.models import Task

            return (await session.execute(select(Task.project_id).where(Task.id == eid))).scalar_one_or_none()
        if entity_type == "rfi":
            from app.modules.rfi.models import RFI

            return (await session.execute(select(RFI.project_id).where(RFI.id == eid))).scalar_one_or_none()
        if entity_type == "ncr":
            from app.modules.ncr.models import NCR

            return (await session.execute(select(NCR.project_id).where(NCR.id == eid))).scalar_one_or_none()
        if entity_type == "submittal":
            from app.modules.submittals.models import Submittal

            return (await session.execute(select(Submittal.project_id).where(Submittal.id == eid))).scalar_one_or_none()
        if entity_type == "punchlist_item":
            from app.modules.punchlist.models import PunchItem

            return (await session.execute(select(PunchItem.project_id).where(PunchItem.id == eid))).scalar_one_or_none()
        if entity_type == "inspection":
            from app.modules.inspections.models import QualityInspection

            return (
                await session.execute(select(QualityInspection.project_id).where(QualityInspection.id == eid))
            ).scalar_one_or_none()
        if entity_type == "meeting":
            from app.modules.meetings.models import Meeting

            return (await session.execute(select(Meeting.project_id).where(Meeting.id == eid))).scalar_one_or_none()
        if entity_type == "transmittal":
            from app.modules.transmittals.models import Transmittal

            return (
                await session.execute(select(Transmittal.project_id).where(Transmittal.id == eid))
            ).scalar_one_or_none()
        if entity_type == "bim_model":
            from app.modules.bim_hub.models import BIMModel

            return (await session.execute(select(BIMModel.project_id).where(BIMModel.id == eid))).scalar_one_or_none()
        if entity_type == "bcf_topic":
            from app.modules.bcf.models import BCFTopic

            return (await session.execute(select(BCFTopic.project_id).where(BCFTopic.id == eid))).scalar_one_or_none()

        # ── One FK hop to reach project_id ──────────────────────────────
        if entity_type == "boq_position":
            from app.modules.boq.models import BOQ, Position

            return (
                await session.execute(
                    select(BOQ.project_id).join(Position, Position.boq_id == BOQ.id).where(Position.id == eid)
                )
            ).scalar_one_or_none()
        if entity_type == "bim_element":
            from app.modules.bim_hub.models import BIMElement, BIMModel

            return (
                await session.execute(
                    select(BIMModel.project_id)
                    .join(BIMElement, BIMElement.model_id == BIMModel.id)
                    .where(BIMElement.id == eid)
                )
            ).scalar_one_or_none()
        if entity_type == "schedule_activity":
            from app.modules.schedule.models import Activity, Schedule

            return (
                await session.execute(
                    select(Schedule.project_id)
                    .join(Activity, Activity.schedule_id == Schedule.id)
                    .where(Activity.id == eid)
                )
            ).scalar_one_or_none()
        if entity_type == "requirement":
            from app.modules.requirements.models import Requirement, RequirementSet

            return (
                await session.execute(
                    select(RequirementSet.project_id)
                    .join(Requirement, Requirement.requirement_set_id == RequirementSet.id)
                    .where(Requirement.id == eid)
                )
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - resolution failed; treat as unresolved (fail closed)
        logger.debug("collaboration entity resolve failed for %s/%s", entity_type, entity_id)
        return None
    # Allow-listed type with no project linkage handled above. Returning None
    # makes the caller fail closed rather than leaving the type silently
    # ungated.
    return None


async def _resolve_built_project_id(key: str, eid: uuid.UUID, session: SessionDep) -> uuid.UUID | None:
    """The project of a built module's record, when that module takes comments.

    ``None`` - and so a 404 - unless the module is installed by the builder,
    loaded, project-scoped and has comments turned on in its spec. Which table
    to read comes from that spec, never from the request.
    """
    from sqlalchemy import select

    from app.modules.module_builder.runtime import loaded_built_module

    built = loaded_built_module(key)
    if built is None or not built.spec.features.comments or not built.spec.entity.project_scoped:
        return None
    model = built.model
    return (await session.execute(select(model.project_id).where(model.id == eid))).scalar_one_or_none()


async def _may_read_built(key: str, user_id: str, session: SessionDep) -> bool:
    """The built module's own read permission, decided as ``RequirePermission`` decides it."""
    from app.core.permissions import permission_registry
    from app.modules.module_builder.links import caller_for

    caller = await caller_for(session, user_id)
    if caller.user_id is None:
        return False
    return caller.is_admin or bool(permission_registry.role_has_permission(caller.role, f"{key}.read"))


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
    avoids leaking UUID existence). For every other allow-listed target we
    resolve the owning project and gate on it. If the type cannot be resolved
    to a project (unknown id, deleted row, or a type with no project linkage)
    we fail CLOSED with a 404, matching the IDOR-404 convention and closing
    the cross-tenant read where any ``collaboration.read`` holder could
    enumerate another tenant's threads by entity id.
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
    built_key = _built_key(entity_type)
    if resolved is not None and built_key is not None and not await _may_read_built(built_key, user_id, session):
        # Someone who may not open the record in its module may not read or
        # write its thread either. Answered like a missing record.
        resolved = None
    if resolved is not None and built_key is not None:
        # The project refusal says "Project not found", which would tell the
        # caller the record exists. A built record answers exactly as a
        # missing one does, as its own module's routes do.
        try:
            await verify_project_access(resolved, str(user_id), session)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found") from None
        return
    if resolved is None:
        # Fail closed: a target we cannot tie to a project the caller can
        # reach is treated as not found (never silently ungated).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )
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
    """List top-level comments for an entity (replies loaded as nested)."""
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
    # A comment can carry a nested viewpoint whose entity_type/entity_id are
    # independent free-text fields the service persists verbatim. The standalone
    # POST /viewpoints/ path runs both the allowlist check and the access check
    # on those fields, so mirror it here. Otherwise an unsupported entity_type
    # could be smuggled in, or the nested viewpoint could reference a missing or
    # cross-tenant entity_id, persisting a dangling viewpoint row the query API
    # rejects.
    if data.viewpoint is not None:
        _validate_entity_type(data.viewpoint.entity_type)
        await _verify_entity_access(
            data.viewpoint.entity_type,
            data.viewpoint.entity_id,
            str(user_id),
            session,
        )
    # Resolve the owning project so the detached comment.created event carries
    # it (the notifications subscriber fans out to project members). When the
    # entity IS a project, its id is the project id; otherwise map through the
    # same resolver the access check used. Resolution failure is non-fatal -
    # the event simply omits the project_id.
    project_id: uuid.UUID | None = None
    try:
        if data.entity_type == "project":
            project_id = uuid.UUID(data.entity_id)
        else:
            project_id = await _resolve_entity_project_id(data.entity_type, data.entity_id, session)
    except (ValueError, TypeError):
        project_id = None
    try:
        comment = await service.create_comment(data, uuid.UUID(user_id), project_id=project_id)
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
