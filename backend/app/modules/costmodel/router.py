"""5D Cost Model API routes.

Endpoints:
    GET    /projects/{project_id}/5d/dashboard          — aggregated KPIs
    GET    /projects/{project_id}/5d/s-curve             — S-curve time series
    GET    /projects/{project_id}/5d/cash-flow           — cash flow data
    GET    /projects/{project_id}/5d/budget              — budget summary by category
    GET    /projects/{project_id}/5d/budget-lines        — detailed budget lines
    POST   /projects/{project_id}/5d/budget-lines        — create budget line
    PATCH  /5d/budget-lines/{line_id}                    — update budget line
    DELETE /5d/budget-lines/{line_id}                    — delete budget line
    POST   /projects/{project_id}/5d/generate-budget     — auto-generate from BOQ
    POST   /projects/{project_id}/5d/snapshots           — create EVM snapshot
    GET    /projects/{project_id}/5d/snapshots           — list snapshots
    POST   /projects/{project_id}/5d/generate-cash-flow  — generate from schedule
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.costmodel.schemas import (
    BudgetLineCreate,
    BudgetLineResponse,
    BudgetLineUpdate,
    BudgetSummary,
    CashFlowCreate,
    CashFlowData,
    CashFlowResponse,
    DashboardResponse,
    SCurveData,
    SnapshotCreate,
    SnapshotResponse,
)
from app.modules.costmodel.service import CostModelService

router = APIRouter()


def _get_service(session: SessionDep) -> CostModelService:
    return CostModelService(session)


# ── Helper: convert model → response ────────────────────────────────────────


def _snapshot_to_response(snap: object) -> SnapshotResponse:
    """Convert a CostSnapshot ORM model to a SnapshotResponse."""
    return SnapshotResponse(
        id=snap.id,  # type: ignore[attr-defined]
        project_id=snap.project_id,  # type: ignore[attr-defined]
        period=snap.period,  # type: ignore[attr-defined]
        planned_cost=float(snap.planned_cost),  # type: ignore[attr-defined]
        earned_value=float(snap.earned_value),  # type: ignore[attr-defined]
        actual_cost=float(snap.actual_cost),  # type: ignore[attr-defined]
        forecast_eac=float(snap.forecast_eac),  # type: ignore[attr-defined]
        spi=float(snap.spi),  # type: ignore[attr-defined]
        cpi=float(snap.cpi),  # type: ignore[attr-defined]
        notes=snap.notes,  # type: ignore[attr-defined]
        metadata_=snap.metadata_,  # type: ignore[attr-defined]
        created_at=snap.created_at,  # type: ignore[attr-defined]
        updated_at=snap.updated_at,  # type: ignore[attr-defined]
    )


def _budget_line_to_response(line: object) -> BudgetLineResponse:
    """Convert a BudgetLine ORM model to a BudgetLineResponse."""
    return BudgetLineResponse(
        id=line.id,  # type: ignore[attr-defined]
        project_id=line.project_id,  # type: ignore[attr-defined]
        boq_position_id=line.boq_position_id,  # type: ignore[attr-defined]
        activity_id=line.activity_id,  # type: ignore[attr-defined]
        category=line.category,  # type: ignore[attr-defined]
        description=line.description,  # type: ignore[attr-defined]
        planned_amount=float(line.planned_amount),  # type: ignore[attr-defined]
        committed_amount=float(line.committed_amount),  # type: ignore[attr-defined]
        actual_amount=float(line.actual_amount),  # type: ignore[attr-defined]
        forecast_amount=float(line.forecast_amount),  # type: ignore[attr-defined]
        period_start=line.period_start,  # type: ignore[attr-defined]
        period_end=line.period_end,  # type: ignore[attr-defined]
        currency=line.currency,  # type: ignore[attr-defined]
        metadata_=line.metadata_,  # type: ignore[attr-defined]
        created_at=line.created_at,  # type: ignore[attr-defined]
        updated_at=line.updated_at,  # type: ignore[attr-defined]
    )


def _cash_flow_to_response(entry: object) -> CashFlowResponse:
    """Convert a CashFlow ORM model to a CashFlowResponse."""
    return CashFlowResponse(
        id=entry.id,  # type: ignore[attr-defined]
        project_id=entry.project_id,  # type: ignore[attr-defined]
        period=entry.period,  # type: ignore[attr-defined]
        category=entry.category,  # type: ignore[attr-defined]
        planned_inflow=float(entry.planned_inflow),  # type: ignore[attr-defined]
        planned_outflow=float(entry.planned_outflow),  # type: ignore[attr-defined]
        actual_inflow=float(entry.actual_inflow),  # type: ignore[attr-defined]
        actual_outflow=float(entry.actual_outflow),  # type: ignore[attr-defined]
        cumulative_planned=float(entry.cumulative_planned),  # type: ignore[attr-defined]
        cumulative_actual=float(entry.cumulative_actual),  # type: ignore[attr-defined]
        metadata_=entry.metadata_,  # type: ignore[attr-defined]
        created_at=entry.created_at,  # type: ignore[attr-defined]
        updated_at=entry.updated_at,  # type: ignore[attr-defined]
    )


# ── Dashboard & Analytics ────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/5d/dashboard",
    response_model=DashboardResponse,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_dashboard(
    project_id: uuid.UUID,
    service: CostModelService = Depends(_get_service),
) -> DashboardResponse:
    """Get aggregated 5D cost dashboard KPIs for a project."""
    return await service.get_dashboard(project_id)


@router.get(
    "/projects/{project_id}/5d/s-curve",
    response_model=SCurveData,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_s_curve(
    project_id: uuid.UUID,
    service: CostModelService = Depends(_get_service),
) -> SCurveData:
    """Get S-curve time series data for chart visualisation."""
    return await service.get_s_curve(project_id)


@router.get(
    "/projects/{project_id}/5d/cash-flow",
    response_model=CashFlowData,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_cash_flow(
    project_id: uuid.UUID,
    service: CostModelService = Depends(_get_service),
) -> CashFlowData:
    """Get monthly cash flow data for chart display."""
    return await service.get_cash_flow(project_id)


# ── Budget ───────────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/5d/budget",
    response_model=BudgetSummary,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_budget_summary(
    project_id: uuid.UUID,
    service: CostModelService = Depends(_get_service),
) -> BudgetSummary:
    """Get budget summary grouped by cost category."""
    return await service.get_budget_summary(project_id)


@router.get(
    "/projects/{project_id}/5d/budget-lines",
    response_model=list[BudgetLineResponse],
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def list_budget_lines(
    project_id: uuid.UUID,
    category: str | None = Query(default=None, description="Filter by cost category"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    service: CostModelService = Depends(_get_service),
) -> list[BudgetLineResponse]:
    """List detailed budget lines for a project."""
    lines, _ = await service.list_budget_lines(
        project_id, category=category, offset=offset, limit=limit
    )
    return [_budget_line_to_response(line) for line in lines]


@router.post(
    "/projects/{project_id}/5d/budget-lines",
    response_model=BudgetLineResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def create_budget_line(
    project_id: uuid.UUID,
    data: BudgetLineCreate,
    _user_id: CurrentUserId,
    service: CostModelService = Depends(_get_service),
) -> BudgetLineResponse:
    """Create a new budget line for a project."""
    data.project_id = project_id
    line = await service.create_budget_line(data)
    return _budget_line_to_response(line)


@router.patch(
    "/5d/budget-lines/{line_id}",
    response_model=BudgetLineResponse,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def update_budget_line(
    line_id: uuid.UUID,
    data: BudgetLineUpdate,
    service: CostModelService = Depends(_get_service),
) -> BudgetLineResponse:
    """Update a budget line (committed, actual, forecast amounts, etc.)."""
    line = await service.update_budget_line(line_id, data)
    return _budget_line_to_response(line)


@router.delete(
    "/5d/budget-lines/{line_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("costmodel.manage"))],
)
async def delete_budget_line(
    line_id: uuid.UUID,
    service: CostModelService = Depends(_get_service),
) -> None:
    """Delete a budget line."""
    await service.delete_budget_line(line_id)


# ── Budget Generation ────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/generate-budget",
    response_model=list[BudgetLineResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.manage"))],
)
async def generate_budget(
    project_id: uuid.UUID,
    _user_id: CurrentUserId,
    body: dict,
    service: CostModelService = Depends(_get_service),
) -> list[BudgetLineResponse]:
    """Auto-generate budget lines from BOQ positions."""
    boq_id = uuid.UUID(str(body.get("boq_id", "")))
    lines = await service.generate_budget_from_boq(project_id, boq_id)
    return [_budget_line_to_response(line) for line in lines]


# ── Snapshots (EVM) ─────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/snapshots",
    response_model=SnapshotResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def create_snapshot(
    project_id: uuid.UUID,
    data: SnapshotCreate,
    _user_id: CurrentUserId,
    service: CostModelService = Depends(_get_service),
) -> SnapshotResponse:
    """Create a new EVM cost snapshot for a project."""
    data.project_id = project_id
    snapshot = await service.create_snapshot(data)
    return _snapshot_to_response(snapshot)


@router.get(
    "/projects/{project_id}/5d/snapshots",
    response_model=list[SnapshotResponse],
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def list_snapshots(
    project_id: uuid.UUID,
    period_from: str | None = Query(default=None, description="Start period (YYYY-MM)"),
    period_to: str | None = Query(default=None, description="End period (YYYY-MM)"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: CostModelService = Depends(_get_service),
) -> list[SnapshotResponse]:
    """List EVM snapshots for a project, optionally filtered by period range."""
    snapshots, _ = await service.list_snapshots(
        project_id,
        period_from=period_from,
        period_to=period_to,
        offset=offset,
        limit=limit,
    )
    return [_snapshot_to_response(snap) for snap in snapshots]


# ── Cash Flow Generation ────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/generate-cash-flow",
    response_model=list[CashFlowResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.manage"))],
)
async def generate_cash_flow(
    project_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: CostModelService = Depends(_get_service),
) -> list[CashFlowResponse]:
    """Generate cash flow entries by spreading budget across schedule."""
    entries = await service.generate_cash_flow_from_schedule(project_id)
    return [_cash_flow_to_response(entry) for entry in entries]
