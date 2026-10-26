# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report API routes (mounted at ``/api/v1/wip-report``).

Project routes check the permission and then ``verify_project_access``; the portfolio
routes are scoped to the projects the caller can reach.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.wip_report.schemas import (
    ClosePeriodRequest,
    FindingsResponse,
    ForecastRequest,
    ForecastResponse,
    PortfolioResponse,
    WipPeriodResponse,
    WipRow,
)
from app.modules.wip_report.service import WipReportService

router = APIRouter(tags=["wip_report"])

_READ = Depends(RequirePermission("wip_report.read"))
_WRITE = Depends(RequirePermission("wip_report.write"))


async def _portfolio(session: SessionDep, user_id: str, as_of: date | None) -> dict:
    ids = await accessible_project_ids(session, user_id)
    return await WipReportService(session).portfolio(ids, as_of)


@router.get("/portfolio", response_model=PortfolioResponse, dependencies=[_READ])
async def portfolio(session: SessionDep, user_id: CurrentUserId, as_of: date | None = None) -> PortfolioResponse:
    """WIP schedule of every reachable project with a contract, totals per currency."""
    return PortfolioResponse.model_validate(await _portfolio(session, user_id, as_of))


@router.get("/portfolio/export", dependencies=[_READ])
async def export_portfolio(
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: Literal["xlsx", "pdf"] = Query("xlsx", alias="format"),
    as_of: date | None = None,
    project_id: uuid.UUID | None = None,
) -> Response:
    """The schedule as an Excel workbook or a PDF; ``project_id`` limits it to one project."""
    from app.modules.wip_report.exports import to_pdf, to_xlsx

    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        data = await WipReportService(session).portfolio({project_id}, as_of)
    else:
        data = await _portfolio(session, user_id, as_of)
    stamp = (as_of or date.today()).isoformat()
    if fmt == "pdf":
        body, media = to_pdf(data), "application/pdf"
    else:
        body, media = to_xlsx(data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="wip-schedule-{stamp}.{fmt}"'},
    )


@router.get("/projects/{project_id}/live", response_model=WipRow, dependencies=[_READ])
async def live_row(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, as_of: date | None = None
) -> WipRow:
    """The project's WIP row computed now from contracts, change orders, cost report and billings."""
    await verify_project_access(project_id, user_id, session)
    return WipRow.model_validate(await WipReportService(session).row(project_id, as_of))


@router.get("/projects/{project_id}/periods", response_model=list[WipPeriodResponse], dependencies=[_READ])
async def list_periods(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[WipPeriodResponse]:
    await verify_project_access(project_id, user_id, session)
    rows = await WipReportService(session).list_periods(project_id)
    return [WipPeriodResponse.model_validate(r) for r in rows]


@router.post("/projects/{project_id}/periods", response_model=WipPeriodResponse, status_code=201, dependencies=[_WRITE])
async def close_period(
    project_id: uuid.UUID, body: ClosePeriodRequest, session: SessionDep, user_id: CurrentUserId
) -> WipPeriodResponse:
    """Close a month: snapshot the WIP row at its last day."""
    await verify_project_access(project_id, user_id, session)
    snap = await WipReportService(session).close_period(project_id, body.period, user_id, body.notes)
    await session.commit()
    await session.refresh(snap)
    return WipPeriodResponse.model_validate(snap)


@router.delete("/projects/{project_id}/periods/{period}", status_code=204, dependencies=[_WRITE])
async def reopen_period(project_id: uuid.UUID, period: str, session: SessionDep, user_id: CurrentUserId) -> Response:
    """Reopen the latest closed month (its snapshot is removed)."""
    await verify_project_access(project_id, user_id, session)
    await WipReportService(session).reopen_period(project_id, period)
    await session.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/forecast", response_model=ForecastResponse, dependencies=[_READ])
async def get_forecast(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ForecastResponse:
    await verify_project_access(project_id, user_id, session)
    row = await WipReportService(session).forecast(project_id)
    return ForecastResponse(estimated_cost=row.estimated_cost if row else None, note=row.note if row else None)


@router.put("/projects/{project_id}/forecast", response_model=ForecastResponse, dependencies=[_WRITE])
async def set_forecast(
    project_id: uuid.UUID, body: ForecastRequest, session: SessionDep, user_id: CurrentUserId
) -> ForecastResponse:
    """Set the estimate at completion used instead of the cost report forecast; null clears it."""
    await verify_project_access(project_id, user_id, session)
    row = await WipReportService(session).set_forecast(project_id, body.estimated_cost, body.note, user_id)
    await session.commit()
    return ForecastResponse(estimated_cost=row.estimated_cost if row else None, note=row.note if row else None)


@router.get("/projects/{project_id}/validation", response_model=FindingsResponse, dependencies=[_READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, as_of: date | None = None
) -> FindingsResponse:
    """Failing WIP rules on the live row."""
    await verify_project_access(project_id, user_id, session)
    return FindingsResponse.model_validate({"findings": await WipReportService(session).findings(project_id, as_of)})
