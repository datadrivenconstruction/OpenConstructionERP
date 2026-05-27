# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Smart Views API routes — mounted by the loader at ``/api/v1/smart-views``.

Endpoints
    POST   /                              → create
    GET    /?scope_type=...&scope_id=...  → list (scope filters optional)
    GET    /{view_id}                     → fetch
    PUT    /{view_id}                     → partial update
    DELETE /{view_id}                     → delete
    POST   /{view_id}/evaluate            → run rules against a BIM model

Auth: ``RequirePermission`` enforces the RBAC verb; the service layer
applies the per-row scoping (user-/project-/federation- visibility).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.smart_views.schemas import (
    SmartViewCreate,
    SmartViewEvaluateResponse,
    SmartViewPresetSummary,
    SmartViewResponse,
    SmartViewShareInfo,
    SmartViewUpdate,
)
from app.modules.smart_views.service import SmartViewService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Smart Views"])


def _get_service(session: SessionDep) -> SmartViewService:
    return SmartViewService(session)


def _user_uuid(user_id: str) -> uuid.UUID:
    """Coerce the JWT subject claim to a UUID — 401 on garbage tokens.

    Mirrors the conversion every other module does at the router edge
    so that downstream service code can assume ``uuid.UUID`` typing.
    """
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        ) from exc


@router.post(
    "/",
    response_model=SmartViewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("smart_views.create"))],
)
async def create_smart_view(
    payload: SmartViewCreate,
    user_id: CurrentUserId,
    service: SmartViewService = Depends(_get_service),
) -> SmartViewResponse:
    """Create a SmartView under the requested scope."""
    return await service.create_view(payload, user_id=_user_uuid(user_id))


@router.get(
    "/",
    response_model=list[SmartViewResponse],
    dependencies=[Depends(RequirePermission("smart_views.read"))],
)
async def list_smart_views(
    user_id: CurrentUserId,
    scope_type: str | None = Query(default=None),
    scope_id: uuid.UUID | None = Query(default=None),
    service: SmartViewService = Depends(_get_service),
) -> list[SmartViewResponse]:
    """List every SmartView the caller is allowed to see.

    Optional ``scope_type`` / ``scope_id`` query parameters narrow the
    result to a single scope row (the BIM viewer's per-model use case).
    """
    return await service.list_views(
        user_id=_user_uuid(user_id),
        scope_type=scope_type,
        scope_id=scope_id,
    )


@router.get(
    "/{view_id}",
    response_model=SmartViewResponse,
    dependencies=[Depends(RequirePermission("smart_views.read"))],
)
async def get_smart_view(
    view_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SmartViewService = Depends(_get_service),
) -> SmartViewResponse:
    """Fetch one SmartView by id. 404 on miss / no-visibility."""
    return await service.get_view(view_id, user_id=_user_uuid(user_id))


@router.put(
    "/{view_id}",
    response_model=SmartViewResponse,
    dependencies=[Depends(RequirePermission("smart_views.update"))],
)
async def update_smart_view(
    view_id: uuid.UUID,
    payload: SmartViewUpdate,
    user_id: CurrentUserId,
    service: SmartViewService = Depends(_get_service),
) -> SmartViewResponse:
    """Partial-update a SmartView (authoring user only)."""
    return await service.update_view(view_id, payload, user_id=_user_uuid(user_id))


@router.delete(
    "/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("smart_views.delete"))],
)
async def delete_smart_view(
    view_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SmartViewService = Depends(_get_service),
) -> None:
    """Delete a SmartView (authoring user only)."""
    await service.delete_view(view_id, user_id=_user_uuid(user_id))


@router.post(
    "/{view_id}/evaluate",
    response_model=SmartViewEvaluateResponse,
    dependencies=[Depends(RequirePermission("smart_views.read"))],
)
async def evaluate_smart_view(
    view_id: uuid.UUID,
    user_id: CurrentUserId,
    model_id: uuid.UUID = Query(...),
    service: SmartViewService = Depends(_get_service),
) -> SmartViewEvaluateResponse:
    """Evaluate a SmartView against a specific BIM model's elements."""
    return await service.evaluate(view_id, model_id, user_id=_user_uuid(user_id))


# ── Presets ────────────────────────────────────────────────────────────


class _InstallPresetRequest(BaseModel):
    """Body for ``POST /smart-views/presets/{preset_id}/install``.

    The caller picks the target scope explicitly; the same preset can be
    installed once for the user's My-views and again at project scope.
    """

    scope_type: str = Field(..., pattern="^(user|project|federation)$")
    scope_id: uuid.UUID


@router.get(
    "/presets",
    response_model=list[SmartViewPresetSummary],
    dependencies=[Depends(RequirePermission("smart_views.read"))],
)
async def list_smart_view_presets() -> list[SmartViewPresetSummary]:
    """List the built-in preset catalogue (static, no DB hit)."""
    return SmartViewService.list_presets()


@router.post(
    "/presets/{preset_id}/install",
    response_model=SmartViewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("smart_views.create"))],
)
async def install_smart_view_preset(
    preset_id: str,
    payload: _InstallPresetRequest,
    user_id: CurrentUserId,
    service: SmartViewService = Depends(_get_service),
) -> SmartViewResponse:
    """Materialise a preset as a new SmartView under the given scope."""
    return await service.install_preset(
        preset_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        user_id=_user_uuid(user_id),
    )


# ── Share-by-link ──────────────────────────────────────────────────────


@router.post(
    "/{view_id}/share",
    response_model=SmartViewShareInfo,
    dependencies=[Depends(RequirePermission("smart_views.update"))],
)
async def create_smart_view_share(
    view_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SmartViewService = Depends(_get_service),
) -> SmartViewShareInfo:
    """Generate (or rotate) a signed share token for an owned view."""
    return await service.create_share_token(view_id, user_id=_user_uuid(user_id))


@router.delete(
    "/{view_id}/share",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("smart_views.update"))],
)
async def revoke_smart_view_share(
    view_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SmartViewService = Depends(_get_service),
) -> None:
    """Null the view's share token; existing links stop working."""
    await service.revoke_share_token(view_id, user_id=_user_uuid(user_id))


@router.get(
    "/shared/{token}",
    response_model=SmartViewResponse,
)
async def resolve_smart_view_share(
    token: str,
    service: SmartViewService = Depends(_get_service),
) -> SmartViewResponse:
    """UNAUTHENTICATED — resolve a share token to a SmartView.

    No ``RequirePermission`` gate: the signed token IS the auth. We
    deliberately do NOT include the token in the response (caller
    already holds it; re-exposing it would let a screenshot leak the
    URL embed).
    """
    return await service.resolve_share_token(token)
