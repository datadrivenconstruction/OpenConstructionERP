"""Asset Operations API (auto-mounted at /api/v1/assets).

Operational-phase intelligence on the BIM-sourced asset register:

    GET  /portfolio?project_id=...          KPI roll-up across all assets
    GET  /?project_id=...                    health-enriched, filtered list
    GET  /discover?project_id=...            ranked asset candidates
    POST /warranty-alerts?project_id=...     scan + optional notify dispatch
    POST /{element_id}/service-log           append a maintenance event

Reads ride ``assets.read`` (VIEWER). Dispatching alerts rides
``assets.alert`` (MANAGER). Every endpoint runs the per-project access
check so a viewer of project A cannot read assets of project B.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.assets.schemas import (
    AssetListResponse,
    DiscoveryResponse,
    PortfolioSummary,
    ServiceLogEntryRequest,
    ServiceLogResponse,
    WarrantyAlertRequest,
    WarrantyAlertResponse,
)
from app.modules.assets.service import AssetOpsService

router = APIRouter(tags=["assets"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> AssetOpsService:
    return AssetOpsService(session)


@router.get("/portfolio", response_model=PortfolioSummary)
async def get_portfolio(
    project_id: uuid.UUID = Query(..., description="Scope the roll-up to this project"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("assets.read")),
    service: AssetOpsService = Depends(_get_service),
) -> PortfolioSummary:
    """KPI roll-up across every tracked asset in the project."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.portfolio_summary(project_id)


@router.get("/", response_model=AssetListResponse)
async def list_assets(
    project_id: uuid.UUID = Query(...),
    warranty_status: str | None = Query(default=None, description="ok|expiring|expired|unknown"),
    maintenance_status: str | None = Query(default=None, description="ok|due|overdue|unknown"),
    operational_status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=200),
    sort: str = Query(default="attention", pattern="^(attention|name|warranty)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("assets.read")),
    service: AssetOpsService = Depends(_get_service),
) -> AssetListResponse:
    """Health-enriched, filtered, paginated tracked-asset list."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.list_assets(
        project_id,
        warranty_status=warranty_status,
        maintenance_status=maintenance_status,
        operational_status=operational_status,
        search=search,
        sort=sort,
        offset=offset,
        limit=limit,
    )


@router.get("/discover", response_model=DiscoveryResponse)
async def discover_assets(
    project_id: uuid.UUID = Query(...),
    model_id: uuid.UUID | None = Query(default=None, description="Restrict scan to one model"),
    threshold: int = Query(default=35, ge=0, le=100),
    result_limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("assets.read")),
    service: AssetOpsService = Depends(_get_service),
) -> DiscoveryResponse:
    """Rank BIM elements as likely managed assets for bulk promotion."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.discover_candidates(
        project_id,
        model_id=model_id,
        threshold=threshold,
        result_limit=result_limit,
    )


@router.post("/warranty-alerts", response_model=WarrantyAlertResponse)
async def warranty_alerts(
    payload: WarrantyAlertRequest,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("assets.alert")),
    service: AssetOpsService = Depends(_get_service),
) -> WarrantyAlertResponse:
    """Scan for expiring / expired warranties; optionally notify the team."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.warranty_alerts(
        project_id,
        lead_days=payload.lead_days,
        dispatch=payload.dispatch,
        actor_user_id=user_id,
    )


@router.post("/{element_id}/service-log", response_model=ServiceLogResponse)
async def append_service_log(
    element_id: uuid.UUID,
    payload: ServiceLogEntryRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.update")),
    service: AssetOpsService = Depends(_get_service),
) -> ServiceLogResponse:
    """Append a maintenance / service event to an asset's history.

    Persisted into ``asset_info.service_log`` through the BIM Hub element
    repository, so no new table is required.
    """
    entry = payload.model_dump(exclude_none=True)
    entry["logged_by"] = user_id
    return await service.append_service_log(element_id, entry=entry, actor_user_id=user_id)
