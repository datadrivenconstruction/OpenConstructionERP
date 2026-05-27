# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP routes for the file-distribution module.

Mounted by the module loader at ``/api/v1/file-distribution``.

Two sub-namespaces:

* ``GET  /search/``               — cross-project ranked file search
* ``GET  /lists/``                — list distribution lists
* ``POST /lists/``                — create
* ``PATCH /lists/{id}/``          — update
* ``DELETE /lists/{id}/``         — delete
* ``POST /lists/{id}/members/``   — add member
* ``DELETE /lists/{lid}/members/{mid}/`` — remove member
* ``GET  /subscriptions/``        — list user's subscriptions
* ``POST /subscriptions/``        — subscribe to folder/kind
* ``DELETE /subscriptions/{id}/``
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.file_distribution.schemas import (
    DistributionListCreate,
    DistributionListListResponse,
    DistributionListResponse,
    DistributionListUpdate,
    DistributionMemberCreate,
    DistributionMemberResponse,
    SearchResponse,
    SubscriptionCreate,
    SubscriptionListResponse,
    SubscriptionResponse,
)
from app.modules.file_distribution.service import (
    CrossProjectSearchService,
    DistributionConflictError,
    DistributionListService,
    DistributionNotFoundError,
    DistributionValidationError,
    SubscriptionService,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier",
        ) from exc


async def _resolve_accessible_project_ids(
    session,  # type: ignore[no-untyped-def]
    user_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Return the set of project ids the caller can see.

    Mirrors ``verify_project_access`` semantics: admins see every
    project, everyone else only their own. Project membership outside
    ownership is a separate concern handled by the documents module
    folder-permissions service — when that service is wired the
    callback used here can be expanded; for now ownership is the safe
    minimum.
    """
    from sqlalchemy import select as _select

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = await session.get(User, user_id)
    is_admin = bool(user is not None and getattr(user, "role", "") == "admin")
    if is_admin:
        rows = await session.execute(_select(Project.id))
    else:
        rows = await session.execute(
            _select(Project.id).where(Project.owner_id == user_id),
        )
    return [r[0] for r in rows.all()]


# ── Cross-project search ─────────────────────────────────────────────────────


@router.get(
    "/search/",
    response_model=SearchResponse,
    summary="Cross-project ranked file search",
    dependencies=[Depends(RequirePermission("file_distribution.read"))],
)
async def search_files(
    session: SessionDep,
    current_user_id: CurrentUserId,
    q: str = Query(..., min_length=1, max_length=255),
    kinds: str | None = Query(
        default=None,
        description=("Comma-separated subset of `document,sheet,photo`. Omit to search all three."),
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> SearchResponse:
    user_uuid = _user_uuid(current_user_id)
    allowed = await _resolve_accessible_project_ids(session, user_uuid)
    kinds_list = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    service = CrossProjectSearchService(session)
    hits, used_index = await service.search(
        q=q,
        allowed_project_ids=allowed,
        kinds=kinds_list,
        limit=limit,
    )
    return SearchResponse(items=hits, total=len(hits), used_content_index=used_index)


# ── Distribution lists ───────────────────────────────────────────────────────


def _list_to_response(
    row,
    *,
    current_user_id: uuid.UUID,
) -> DistributionListResponse:
    return DistributionListResponse(
        id=row.id,
        owner_id=row.owner_id,
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        is_shared=row.is_shared,
        members=[
            DistributionMemberResponse(
                id=m.id,
                list_id=m.list_id,
                email=m.email,
                display_name=m.display_name,
                role=m.role,
                created_at=m.created_at,
            )
            for m in (row.members or [])
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
        is_own=row.owner_id == current_user_id,
    )


@router.get(
    "/lists/",
    response_model=DistributionListListResponse,
    summary="List distribution lists visible to the caller",
    dependencies=[Depends(RequirePermission("file_distribution.read"))],
)
async def list_distribution_lists(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
) -> DistributionListListResponse:
    user_uuid = _user_uuid(current_user_id)
    service = DistributionListService(session)
    rows = await service.list_for_user(user_id=user_uuid, project_id=project_id)
    return DistributionListListResponse(
        items=[_list_to_response(r, current_user_id=user_uuid) for r in rows],
        total=len(rows),
    )


@router.post(
    "/lists/",
    response_model=DistributionListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a distribution list",
    dependencies=[Depends(RequirePermission("file_distribution.write"))],
)
async def create_distribution_list(
    payload: DistributionListCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> DistributionListResponse:
    user_uuid = _user_uuid(current_user_id)
    service = DistributionListService(session)
    try:
        row = await service.create(payload, user_uuid)
    except DistributionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _list_to_response(row, current_user_id=user_uuid)


@router.patch(
    "/lists/{list_id}/",
    response_model=DistributionListResponse,
    summary="Update a distribution list (owner only)",
    dependencies=[Depends(RequirePermission("file_distribution.write"))],
)
async def update_distribution_list(
    list_id: uuid.UUID,
    payload: DistributionListUpdate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> DistributionListResponse:
    user_uuid = _user_uuid(current_user_id)
    service = DistributionListService(session)
    try:
        row = await service.update(list_id, payload, user_uuid)
    except DistributionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="List not found",
        ) from exc
    except DistributionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _list_to_response(row, current_user_id=user_uuid)


@router.delete(
    "/lists/{list_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a distribution list (owner only)",
    dependencies=[Depends(RequirePermission("file_distribution.write"))],
)
async def delete_distribution_list(
    list_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    user_uuid = _user_uuid(current_user_id)
    service = DistributionListService(session)
    try:
        await service.delete(list_id, user_uuid)
    except DistributionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="List not found",
        ) from exc


# ── Members ──────────────────────────────────────────────────────────────────


@router.post(
    "/lists/{list_id}/members/",
    response_model=DistributionMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to a distribution list",
    dependencies=[Depends(RequirePermission("file_distribution.write"))],
)
async def add_distribution_member(
    list_id: uuid.UUID,
    payload: DistributionMemberCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> DistributionMemberResponse:
    user_uuid = _user_uuid(current_user_id)
    service = DistributionListService(session)
    try:
        member = await service.add_member(list_id, payload, user_uuid)
    except DistributionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="List not found",
        ) from exc
    except DistributionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return DistributionMemberResponse(
        id=member.id,
        list_id=member.list_id,
        email=member.email,
        display_name=member.display_name,
        role=member.role,
        created_at=member.created_at,
    )


@router.delete(
    "/lists/{list_id}/members/{member_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from a distribution list",
    dependencies=[Depends(RequirePermission("file_distribution.write"))],
)
async def remove_distribution_member(
    list_id: uuid.UUID,
    member_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    user_uuid = _user_uuid(current_user_id)
    service = DistributionListService(session)
    try:
        await service.remove_member(list_id, member_id, user_uuid)
    except DistributionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        ) from exc


# ── Subscriptions ────────────────────────────────────────────────────────────


def _sub_to_response(row) -> SubscriptionResponse:  # type: ignore[no-untyped-def]
    return SubscriptionResponse(
        id=row.id,
        project_id=row.project_id,
        file_kind=row.file_kind,
        subscriber_email=row.subscriber_email,
        subscriber_user_id=row.subscriber_user_id,
        notify_on=list(row.notify_on or []),
        active=row.active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/subscriptions/",
    response_model=SubscriptionListResponse,
    summary="List the caller's subscriptions",
    dependencies=[Depends(RequirePermission("file_distribution.read"))],
)
async def list_subscriptions(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
) -> SubscriptionListResponse:
    user_uuid = _user_uuid(current_user_id)
    service = SubscriptionService(session)
    if project_id is None:
        rows = await service.list_for_user_global(user_id=user_uuid)
    else:
        rows = await service.list_for_project(
            project_id=project_id,
            user_id=user_uuid,
        )
    return SubscriptionListResponse(
        items=[_sub_to_response(r) for r in rows],
        total=len(rows),
    )


@router.post(
    "/subscriptions/",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to a project + file-kind",
    dependencies=[Depends(RequirePermission("file_distribution.subscribe"))],
)
async def create_subscription(
    payload: SubscriptionCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> SubscriptionResponse:
    user_uuid = _user_uuid(current_user_id)
    service = SubscriptionService(session)
    try:
        sub = await service.create(payload, user_uuid)
    except DistributionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except DistributionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _sub_to_response(sub)


@router.delete(
    "/subscriptions/{subscription_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unsubscribe",
    dependencies=[Depends(RequirePermission("file_distribution.subscribe"))],
)
async def delete_subscription(
    subscription_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    user_uuid = _user_uuid(current_user_id)
    service = SubscriptionService(session)
    try:
        await service.delete(subscription_id, user_uuid)
    except DistributionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        ) from exc
