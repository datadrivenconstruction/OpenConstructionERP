# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cash-flow forecast endpoints, mounted on the cost model router.

GET  /projects/{project_id}/5d/cashflow-forecast/            - project forecast
GET  /projects/{project_id}/5d/cashflow-forecast/export/     - project workbook
POST /projects/{project_id}/5d/cashflow-forecast/evaluate/   - run rules, publish events
GET  /5d/cashflow-forecast/portfolio/                        - portfolio per currency
GET  /5d/cashflow-forecast/portfolio/export/                 - portfolio workbook
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, accessible_project_ids, verify_project_access
from app.modules.costmodel.cashflow_forecast import Scenario
from app.modules.costmodel.cashflow_forecast_schemas import (
    CashFlowEvaluation,
    PortfolioCashFlowForecast,
    ProjectCashFlowForecast,
)
from app.modules.costmodel.cashflow_forecast_service import (
    CashFlowForecastService,
    parse_pct,
    portfolio_workbook,
    project_workbook,
)

router = APIRouter(tags=["costmodel"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PCT = r"^-?\d{1,3}(\.\d{1,4})?$"
_MONEY = r"^\d{1,15}(\.\d{1,2})?$"


def _scenario(receipt_delay_days: int, cost_overrun_pct: str) -> Scenario:
    return Scenario(receipt_delay_days=receipt_delay_days, cost_overrun_pct=parse_pct(cost_overrun_pct))


def _locale() -> str:
    from app.core.i18n import get_locale

    return get_locale()


async def _project_or_404(
    session: SessionDep, project_id: uuid.UUID, scenario: Scenario, threshold: str | None
) -> ProjectCashFlowForecast:
    result = await CashFlowForecastService(session).project(
        project_id, scenario, threshold=Decimal(threshold) if threshold else None, locale=_locale()
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result


@router.get(
    "/projects/{project_id}/5d/cashflow-forecast/",
    response_model=ProjectCashFlowForecast,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_cashflow_forecast(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    receipt_delay_days: int = Query(default=0, ge=0, le=730),
    cost_overrun_pct: str = Query(default="0", pattern=_PCT),
    threshold: str | None = Query(default=None, pattern=_MONEY),
) -> ProjectCashFlowForecast:
    """Monthly cash in and out, actuals against plan, cumulative position and peak funding, per currency."""
    await verify_project_access(project_id, user_id, session)
    return await _project_or_404(session, project_id, _scenario(receipt_delay_days, cost_overrun_pct), threshold)


@router.get(
    "/projects/{project_id}/5d/cashflow-forecast/export/",
    response_model=None,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def export_cashflow_forecast(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    format: str = Query(default="xlsx", pattern="^xlsx$"),  # noqa: A002 - the query parameter every export takes
    receipt_delay_days: int = Query(default=0, ge=0, le=730),
    cost_overrun_pct: str = Query(default="0", pattern=_PCT),
) -> Response:
    """The project forecast as a workbook, one sheet per currency."""
    from app.core.content_disposition import attachment_disposition

    await verify_project_access(project_id, user_id, session)
    forecast = await _project_or_404(session, project_id, _scenario(receipt_delay_days, cost_overrun_pct), None)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=project_workbook(forecast, _locale()),
        media_type=_XLSX,
        headers={"Content-Disposition": attachment_disposition(f"cashflow_forecast_{stamp}.{format}")},
    )


@router.post(
    "/projects/{project_id}/5d/cashflow-forecast/evaluate/",
    response_model=CashFlowEvaluation,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def evaluate_cashflow_forecast(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    receipt_delay_days: int = Query(default=0, ge=0, le=730),
    cost_overrun_pct: str = Query(default="0", pattern=_PCT),
    threshold: str | None = Query(default=None, pattern=_MONEY),
) -> CashFlowEvaluation:
    """Run the cash-flow rules and publish an event for each finding."""
    await verify_project_access(project_id, user_id, session)
    result = await CashFlowForecastService(session).evaluate(
        project_id,
        _scenario(receipt_delay_days, cost_overrun_pct),
        threshold=Decimal(threshold) if threshold else None,
        locale=_locale(),
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result


async def _portfolio(
    session: SessionDep, user_id: str, receipt_delay_days: int, cost_overrun_pct: str
) -> PortfolioCashFlowForecast:
    scope = await accessible_project_ids(session, user_id)
    ids = None if scope is None else [uuid.UUID(str(p)) for p in scope]
    return await CashFlowForecastService(session).portfolio(
        ids, _scenario(receipt_delay_days, cost_overrun_pct), locale=_locale()
    )


@router.get(
    "/5d/cashflow-forecast/portfolio/",
    response_model=PortfolioCashFlowForecast,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_portfolio_cashflow_forecast(
    user_id: CurrentUserId,
    session: SessionDep,
    receipt_delay_days: int = Query(default=0, ge=0, le=730),
    cost_overrun_pct: str = Query(default="0", pattern=_PCT),
) -> PortfolioCashFlowForecast:
    """Every active project the caller can see, summed per currency; currencies are never mixed."""
    return await _portfolio(session, user_id, receipt_delay_days, cost_overrun_pct)


@router.get(
    "/5d/cashflow-forecast/portfolio/export/",
    response_model=None,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def export_portfolio_cashflow_forecast(
    user_id: CurrentUserId,
    session: SessionDep,
    format: str = Query(default="xlsx", pattern="^xlsx$"),  # noqa: A002 - the query parameter every export takes
    receipt_delay_days: int = Query(default=0, ge=0, le=730),
    cost_overrun_pct: str = Query(default="0", pattern=_PCT),
) -> Response:
    """The portfolio forecast as a workbook, one sheet per currency."""
    from app.core.content_disposition import attachment_disposition

    forecast = await _portfolio(session, user_id, receipt_delay_days, cost_overrun_pct)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=portfolio_workbook(forecast, _locale()),
        media_type=_XLSX,
        headers={"Content-Disposition": attachment_disposition(f"portfolio_cashflow_{stamp}.{format}")},
    )
