"""Full EVM API routes.

Endpoints:
    GET    /forecasts              — List EVM forecasts
    POST   /forecasts/calculate    — Calculate EVM forecast from snapshots (auth required)
    GET    /s-curve-data           — Get S-curve data for charting
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.full_evm.schemas import (
    EVMCalculateRequest,
    EVMForecastListResponse,
    EVMForecastResponse,
    SCurveDataResponse,
)
from app.modules.full_evm.service import EVMService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> EVMService:
    return EVMService(session)


# ── IDOR protection ───────────────────────────────────────────────────────


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    user_id: str | None,
) -> None:
    """Verify the user owns (or is admin on) the referenced project.

    Every project-scoped EVM endpoint must call this — the service layer
    trusts the project_id and will gladly return cross-tenant data
    otherwise. Mirrors ``finance.router._require_project_access``.
    ``None`` project_id is a no-op (for the list endpoint which may
    choose to aggregate across the caller's own projects).
    """
    if project_id is None:
        return
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        from app.modules.projects.repository import ProjectRepository
        from app.modules.users.repository import UserRepository

        proj_repo = ProjectRepository(session)
        project = await proj_repo.get_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )

        # Admin bypass
        try:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(user_id)
            if user is not None and getattr(user, "role", "") == "admin":
                return
        except Exception:  # noqa: BLE001 — best-effort admin check
            pass

        if str(getattr(project, "owner_id", "")) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not own this project",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Full EVM project access check failed for %s: %s", project_id, exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization check failed",
        )


@router.get(
    "/forecasts/",
    response_model=EVMForecastListResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def list_forecasts(
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    service: EVMService = Depends(_get_service),
) -> EVMForecastListResponse:
    """List EVM forecasts with optional project filter.

    When ``project_id`` is provided we verify ownership before returning
    data. When omitted the list is intentionally empty for non-admin
    callers until an explicit project scope is supplied — preventing
    cross-tenant enumeration.
    """
    if project_id is None:
        # Omitted scope: refuse to dump all forecasts across tenants.
        # Admins can pass an explicit project_id if they need a scoped list.
        return EVMForecastListResponse(items=[], total=0)
    await _verify_project_access(session, project_id, user_id)
    items, total = await service.list_forecasts(project_id=project_id)
    return EVMForecastListResponse(
        items=[EVMForecastResponse.model_validate(f) for f in items],
        total=total,
    )


@router.post(
    "/forecasts/calculate/",
    response_model=EVMForecastResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("full_evm.create"))],
)
async def calculate_forecast(
    data: EVMCalculateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMService = Depends(_get_service),
) -> EVMForecastResponse:
    """Calculate EVM forecast from latest finance EVM snapshot."""
    await _verify_project_access(session, data.project_id, user_id)
    forecast = await service.calculate_forecast(
        project_id=data.project_id,
        forecast_method=data.forecast_method,
    )
    return EVMForecastResponse.model_validate(forecast)


@router.get(
    "/s-curve-data/",
    response_model=SCurveDataResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def get_s_curve_data(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMService = Depends(_get_service),
) -> SCurveDataResponse:
    """Get S-curve data combining EVM snapshots and forecasts for charting."""
    await _verify_project_access(session, project_id, user_id)
    data = await service.get_s_curve_data(project_id)
    return SCurveDataResponse(**data)
