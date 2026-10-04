# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Price-index API routes.

Mounted at ``/api/v1/price-index/`` by the module loader.

Endpoint groups:
    /series/                         - cost-index series CRUD
    /series/{id}/points/             - period/value points under a series
    /location-factors/               - regional cost factors CRUD
    /adjust/                         - batch base-to-current adjustment
    /resource-index/...              - the resource-index method (Russia), see resource_index_router

The reference data is platform-wide, so reads only require an authenticated
user and writes require the ``price_index.manage`` permission. A missing row
returns 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.price_index.models import CostIndexSeries
from app.modules.price_index.resource_index_router import router as resource_index_router
from app.modules.price_index.schemas import (
    AdjustRequest,
    AdjustResponse,
    CostIndexPointCreate,
    CostIndexPointResponse,
    CostIndexPointUpdate,
    CostIndexSeriesCreate,
    CostIndexSeriesDetail,
    CostIndexSeriesResponse,
    CostIndexSeriesUpdate,
    EscalatePreviewRequest,
    EscalatePreviewResponse,
    LocationFactorCreate,
    LocationFactorResponse,
    LocationFactorUpdate,
)
from app.modules.price_index.service import (
    AmbiguousSeriesError,
    PriceIndexService,
    ProjectNotFoundError,
    SeriesNotFoundError,
)

router = APIRouter(tags=["price-index"])
router.include_router(resource_index_router)

_MANAGE = Depends(RequirePermission("price_index.manage"))


def _service(session: SessionDep) -> PriceIndexService:
    return PriceIndexService(session)


def _series_response(series: CostIndexSeries, point_count: int) -> CostIndexSeriesResponse:
    return CostIndexSeriesResponse(
        id=series.id,
        name=series.name,
        description=series.description,
        point_count=point_count,
        created_at=series.created_at,
        updated_at=series.updated_at,
    )


def _series_detail(series: CostIndexSeries) -> CostIndexSeriesDetail:
    points = [CostIndexPointResponse.model_validate(p) for p in series.points]
    return CostIndexSeriesDetail(
        id=series.id,
        name=series.name,
        description=series.description,
        point_count=len(points),
        created_at=series.created_at,
        updated_at=series.updated_at,
        points=points,
    )


# ── Series ───────────────────────────────────────────────────────────────────


@router.get("/series/", response_model=list[CostIndexSeriesResponse])
async def list_series(session: SessionDep, _user_id: CurrentUserId) -> list[CostIndexSeriesResponse]:
    """List every cost-index series with its point count."""
    service = PriceIndexService(session)
    return [_series_response(series, count) for series, count in await service.list_series()]


@router.post(
    "/series/",
    response_model=CostIndexSeriesResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_series(
    data: CostIndexSeriesCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> CostIndexSeriesResponse:
    """Create a new cost-index series."""
    service = PriceIndexService(session)
    series = await service.create_series(data)
    return _series_response(series, 0)


@router.get("/series/{series_id}/", response_model=CostIndexSeriesDetail)
async def get_series(
    series_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> CostIndexSeriesDetail:
    """Get one series with all of its points."""
    service = PriceIndexService(session)
    series = await service.get_series(series_id)
    if series is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost-index series not found")
    return _series_detail(series)


@router.patch("/series/{series_id}/", response_model=CostIndexSeriesResponse, dependencies=[_MANAGE])
async def update_series(
    series_id: uuid.UUID,
    data: CostIndexSeriesUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> CostIndexSeriesResponse:
    """Update a series' name or description."""
    service = PriceIndexService(session)
    series = await service.update_series(series_id, data)
    if series is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost-index series not found")
    return _series_response(series, await service.point_count(series_id))


@router.delete(
    "/series/{series_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MANAGE],
)
async def delete_series(series_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId) -> None:
    """Delete a series and all of its points."""
    service = PriceIndexService(session)
    if not await service.delete_series(series_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost-index series not found")


# ── Points ───────────────────────────────────────────────────────────────────


@router.post(
    "/series/{series_id}/points/",
    response_model=CostIndexPointResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def add_point(
    series_id: uuid.UUID,
    data: CostIndexPointCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> CostIndexPointResponse:
    """Add a period/value point to a series."""
    service = PriceIndexService(session)
    if await service.get_series(series_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost-index series not found")
    point = await service.add_point(series_id, data)
    return CostIndexPointResponse.model_validate(point)


@router.patch(
    "/series/{series_id}/points/{point_id}/",
    response_model=CostIndexPointResponse,
    dependencies=[_MANAGE],
)
async def update_point(
    series_id: uuid.UUID,
    point_id: uuid.UUID,
    data: CostIndexPointUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> CostIndexPointResponse:
    """Update a point's factor or period."""
    service = PriceIndexService(session)
    existing = await service.get_point(point_id)
    if existing is None or existing.series_id != series_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost-index point not found")
    point = await service.update_point(point_id, data)
    assert point is not None  # existence proven above
    return CostIndexPointResponse.model_validate(point)


@router.delete(
    "/series/{series_id}/points/{point_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MANAGE],
)
async def delete_point(
    series_id: uuid.UUID,
    point_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    """Delete a point from a series."""
    service = PriceIndexService(session)
    existing = await service.get_point(point_id)
    if existing is None or existing.series_id != series_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost-index point not found")
    await service.delete_point(point_id)


# ── Location factors ─────────────────────────────────────────────────────────


@router.get("/location-factors/", response_model=list[LocationFactorResponse])
async def list_location_factors(
    session: SessionDep,
    _user_id: CurrentUserId,
) -> list[LocationFactorResponse]:
    """List every regional cost factor."""
    service = PriceIndexService(session)
    return [LocationFactorResponse.model_validate(lf) for lf in await service.list_location_factors()]


@router.post(
    "/location-factors/",
    response_model=LocationFactorResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_location_factor(
    data: LocationFactorCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> LocationFactorResponse:
    """Create a regional cost factor."""
    service = PriceIndexService(session)
    return LocationFactorResponse.model_validate(await service.create_location_factor(data))


@router.patch(
    "/location-factors/{factor_id}/",
    response_model=LocationFactorResponse,
    dependencies=[_MANAGE],
)
async def update_location_factor(
    factor_id: uuid.UUID,
    data: LocationFactorUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> LocationFactorResponse:
    """Update a regional cost factor."""
    service = PriceIndexService(session)
    factor = await service.update_location_factor(factor_id, data)
    if factor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location factor not found")
    return LocationFactorResponse.model_validate(factor)


@router.delete(
    "/location-factors/{factor_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MANAGE],
)
async def delete_location_factor(
    factor_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    """Delete a regional cost factor."""
    service = PriceIndexService(session)
    if not await service.delete_location_factor(factor_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location factor not found")


# ── Adjust ───────────────────────────────────────────────────────────────────


@router.post("/adjust/", response_model=AdjustResponse)
async def adjust(
    request: AdjustRequest,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> AdjustResponse:
    """Bring a batch of amounts to the target period and region.

    Returns each line's temporal factor, location factor, combined applied
    factor and adjusted amount without touching the source data.
    """
    service = PriceIndexService(session)
    try:
        return await service.adjust(request)
    except SeriesNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cost-index series not found",
        ) from exc


# ── Escalate stored rates (preview) ──────────────────────────────────────────


@router.post("/escalate-preview/", response_model=EscalatePreviewResponse)
async def escalate_preview(
    request: EscalatePreviewRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> EscalatePreviewResponse:
    """Preview the estimate's own stored rates escalated to a target date.

    For each selected cost item this returns its base rate, its capture date
    (``price_as_of``), the temporal escalation factor from that date's period to
    the target date's period on the chosen series, and the escalated rate. It is
    strictly read-only: neither the cost items nor the BOQ are modified. An item
    with no ``price_as_of`` (or an unparseable rate, or a period the series does
    not carry) comes back flagged and unescalated rather than guessed.

    Pass ``project_id`` to escalate exactly the rates the project's BOQ
    references instead of the catalogue at large; the result then carries the
    project context.
    """
    # Project scope reads exactly the cost items a project's BOQ references, so
    # it must be gated by project access: without this any authenticated user
    # could read another project's name and the rates its estimate uses. The
    # catalogue scope (no project_id) stays open as platform-wide reference data.
    # verify_project_access returns 404 for both missing and forbidden.
    if request.project_id is not None:
        await verify_project_access(request.project_id, user_id, session)
    service = PriceIndexService(session)
    try:
        return await service.escalate_stored_rates(request)
    except SeriesNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cost-index series not found",
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except AmbiguousSeriesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
