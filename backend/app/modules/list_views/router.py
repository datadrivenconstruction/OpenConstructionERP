# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views API: saved table layouts per list page.

Mounted at ``/api/v1/list-views``. Every call is bounded by the caller's tenant:
a shared view is visible to the tenant only, and only its owner may change it.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.list_views.models import ListView
from app.modules.list_views.schemas import (
    SCOPE_KEY_PATTERN,
    ListViewCreate,
    ListViewResponse,
    ListViewState,
    ListViewUpdate,
)
from app.modules.list_views.service import ListViewError, ListViewService

router = APIRouter(tags=["list_views"])


class ListViewSaved(BaseModel):
    """A saved view plus the warnings its layout raised."""

    view: ListViewResponse
    findings: list[dict[str, Any]]


#: Sharing key of a single-tenant install: every user of the install is one team.
WORKSPACE_TENANT = "workspace"


def _tenant(payload: dict[str, Any]) -> str:
    """The explicit tenant claim when multi-tenancy issues one, else the install."""
    raw = str(payload.get("tenant_id") or "").strip()
    return raw[:36] or WORKSPACE_TENANT


def _service(session: SessionDep, user_id: str, payload: dict[str, Any]) -> ListViewService:
    return ListViewService(session, user_id=uuid.UUID(str(user_id)), tenant_id=_tenant(payload))


def _to_response(view: ListView, user_id: uuid.UUID) -> ListViewResponse:
    return ListViewResponse(
        id=view.id,
        scope_key=view.scope_key,
        name=view.name,
        state=ListViewState.model_validate(view.state or {}),
        is_shared=view.is_shared,
        is_default=view.is_default and view.user_id == user_id,
        is_own=view.user_id == user_id,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _http(exc: ListViewError) -> HTTPException:
    detail: Any = {"message": exc.message, "findings": exc.findings} if exc.findings else exc.message
    return HTTPException(status_code=exc.status, detail=detail)


@router.get(
    "/",
    response_model=list[ListViewResponse],
    dependencies=[Depends(RequirePermission("list_views.read"))],
)
async def list_views(
    session: SessionDep,
    user_id: CurrentUserId,
    user_payload: CurrentUserPayload,
    scope_key: str = Query(pattern=SCOPE_KEY_PATTERN),
) -> list[ListViewResponse]:
    """Own and team-shared views of one list page."""
    service = _service(session, user_id, user_payload)
    return [_to_response(v, service.user_id) for v in await service.list(scope_key)]


@router.post(
    "/",
    response_model=ListViewSaved,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("list_views.create"))],
)
async def create_view(
    payload: ListViewCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    user_payload: CurrentUserPayload,
) -> ListViewSaved:
    """Save the current layout of a list page as a named view."""
    if payload.is_shared:
        await _require_share(session, user_id)
    service = _service(session, user_id, user_payload)
    try:
        view, findings = await service.create(payload)
    except ListViewError as exc:
        raise _http(exc) from exc
    return ListViewSaved(view=_to_response(view, service.user_id), findings=findings)


@router.patch(
    "/{view_id}",
    response_model=ListViewSaved,
    dependencies=[Depends(RequirePermission("list_views.create"))],
)
async def update_view(
    view_id: uuid.UUID,
    payload: ListViewUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    user_payload: CurrentUserPayload,
) -> ListViewSaved:
    """Rename, share, mark as default or overwrite an own view."""
    if payload.is_shared:
        await _require_share(session, user_id)
    service = _service(session, user_id, user_payload)
    try:
        view, findings = await service.update(view_id, payload)
    except ListViewError as exc:
        raise _http(exc) from exc
    return ListViewSaved(view=_to_response(view, service.user_id), findings=findings)


@router.delete(
    "/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("list_views.create"))],
)
async def delete_view(
    view_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    user_payload: CurrentUserPayload,
) -> None:
    """Delete an own view."""
    service = _service(session, user_id, user_payload)
    try:
        await service.delete(view_id)
    except ListViewError as exc:
        raise _http(exc) from exc


async def _require_share(session: SessionDep, user_id: str) -> None:
    """Sharing with the team needs the editor role."""
    from app.core.permissions import permission_registry
    from app.modules.users.models import User

    user = await session.get(User, uuid.UUID(str(user_id)))
    role = getattr(user, "role", None) or "viewer"
    if not permission_registry.role_has_permission(str(role), "list_views.share"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sharing views needs the editor role")
