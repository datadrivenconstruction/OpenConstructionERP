"""Full EVM API routes.

Endpoints:
    GET    /forecasts              — List EVM forecasts
    POST   /forecasts/calculate    — Calculate EVM forecast from snapshots (auth required)
    GET    /s-curve-data           — Get S-curve data for charting
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.full_evm.schemas import (
    EVMCalculateRequest,
    EVMForecastListResponse,
    EVMForecastResponse,
    SCurveDataResponse,
)
from app.modules.full_evm.service import EVMService

router = APIRouter()


def _get_service(session: SessionDep) -> EVMService:
    return EVMService(session)


@router.get("/forecasts/", response_model=EVMForecastListResponse)
async def list_forecasts(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    service: EVMService = Depends(_get_service),
) -> EVMForecastListResponse:
    """List EVM forecasts with optional project filter."""
    items, total = await service.list_forecasts(project_id=project_id)
    return EVMForecastListResponse(
        items=[EVMForecastResponse.model_validate(f) for f in items],
        total=total,
    )


@router.post("/forecasts/calculate/", response_model=EVMForecastResponse, status_code=201)
async def calculate_forecast(
    data: EVMCalculateRequest,
    user_id: CurrentUserId,
    service: EVMService = Depends(_get_service),
) -> EVMForecastResponse:
    """Calculate EVM forecast from latest finance EVM snapshot."""
    forecast = await service.calculate_forecast(
        project_id=data.project_id,
        forecast_method=data.forecast_method,
    )
    return EVMForecastResponse.model_validate(forecast)


@router.get("/s-curve-data/", response_model=SCurveDataResponse)
async def get_s_curve_data(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMService = Depends(_get_service),
) -> SCurveDataResponse:
    """Get S-curve data combining EVM snapshots and forecasts for charting."""
    data = await service.get_s_curve_data(project_id)
    return SCurveDataResponse(**data)
