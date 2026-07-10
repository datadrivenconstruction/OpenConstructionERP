"""Currency / FX API routes.

Endpoints:
    GET  /status/   -- Feed status: rate source, as-of date, cached currencies, network_ok
    GET  /rates/    -- Latest rate map for a base currency (units per 1 base)
    POST /convert/  -- Convert an amount between two currencies (market or PPP)
    POST /refresh/  -- Fetch the live ECB feed now and upsert the cache (costs.update)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.fx.schemas import (
    ConvertRequest,
    ConvertResponse,
    FxRatesResponse,
    FxStatusResponse,
    RefreshResponse,
)
from app.modules.fx.service import FxService, UnknownCurrencyError

router = APIRouter(tags=["fx"])
logger = logging.getLogger(__name__)


def _get_fx_service(session: SessionDep) -> FxService:
    return FxService(session)


@router.get("/status/", response_model=FxStatusResponse)
async def fx_status(
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
) -> FxStatusResponse:
    """Report FX feed status: rate source, freshness, cached currencies and reachability.

    Makes one best-effort probe of the ECB feed for ``network_ok``; a failure is
    reported, never raised.
    """
    return FxStatusResponse(**await service.status())


@router.get("/rates/", response_model=FxRatesResponse)
async def fx_rates(
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    base: str = Query(default="EUR", min_length=3, max_length=3, description="Base currency (ISO 4217)."),
) -> FxRatesResponse:
    """Return the latest rate map for a base currency (units of each currency per 1 base).

    Rates come from the database cache when present, otherwise from the bundled
    seed. Non-EUR bases are rebased from the EUR-based feed.
    """
    try:
        data = await service.get_rates(base)
    except UnknownCurrencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown currency: {exc}",
        ) from exc
    return FxRatesResponse(**data)


@router.post("/convert/", response_model=ConvertResponse)
async def fx_convert(
    body: ConvertRequest,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
) -> ConvertResponse:
    """Convert an amount between two currencies.

    ``mode=market`` uses ECB reference rates (default); ``mode=ppp`` uses World
    Bank purchasing-power-parity factors and may return ``available=false`` when
    a factor is missing, which is a 200 response, not an error.
    """
    try:
        data = await service.convert(
            body.amount,
            body.from_currency,
            body.to_currency,
            mode=body.mode,
        )
    except UnknownCurrencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown currency: {exc}",
        ) from exc
    return ConvertResponse(**data)


@router.post(
    "/refresh/",
    response_model=RefreshResponse,
    dependencies=[Depends(RequirePermission("costs.update"))],
)
async def fx_refresh(
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
) -> RefreshResponse:
    """Fetch the live ECB feed now and upsert the rate cache.

    On a network failure the cache is seeded from the bundled fallback (only when
    empty) and the response records ``network_ok=false``; the endpoint never
    fails on a network error.
    """
    return RefreshResponse(**await service.refresh())
