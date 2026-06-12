"""‌⁠‍5D Cost Model API routes.

Endpoints:
    GET    /projects/{project_id}/5d/dashboard          - aggregated KPIs
    GET    /projects/{project_id}/5d/s-curve             - S-curve time series
    GET    /projects/{project_id}/5d/cash-flow           - cash flow data
    GET    /projects/{project_id}/5d/budget              - budget summary by category
    GET    /projects/{project_id}/5d/budget-lines        - detailed budget lines
    POST   /projects/{project_id}/5d/budget-lines        - create budget line
    PATCH  /5d/budget-lines/{line_id}                    - update budget line
    DELETE /5d/budget-lines/{line_id}                    - delete budget line
    POST   /projects/{project_id}/5d/generate-budget     - auto-generate from BOQ
    POST   /projects/{project_id}/5d/snapshots           - create EVM snapshot
    GET    /projects/{project_id}/5d/snapshots           - list snapshots
    PATCH  /5d/snapshots/{snapshot_id}                   - update snapshot (notes, values)
    POST   /projects/{project_id}/5d/generate-cash-flow  - generate from schedule
    GET    /projects/{project_id}/5d/evm                 - full EVM calculation
    POST   /projects/{project_id}/5d/what-if             - create what-if scenario
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.costmodel.schemas import (
    BudgetLineCreate,
    BudgetLineResponse,
    BudgetLineUpdate,
    BudgetSummary,
    CashFlowData,
    CashFlowResponse,
    ControlAccountCreate,
    ControlAccountResponse,
    ControlAccountUpdate,
    CostLineCreate,
    CostLineResponse,
    CostLineRollupResponse,
    CostLineUpdate,
    DashboardResponse,
    EVMResponse,
    SCurveData,
    SnapshotCreate,
    SnapshotResponse,
    SnapshotUpdate,
    SpineGenerationResult,
    SpineLinkRequest,
    SpineRollupResponse,
    VarianceResponse,
    WhatIfAdjustments,
    WhatIfResult,
)
from app.modules.costmodel.service import CostModelService, CostSpineService

router = APIRouter(tags=["costmodel"])


def _get_service(session: SessionDep) -> CostModelService:
    return CostModelService(session)


def _get_spine_service(session: SessionDep) -> CostSpineService:
    return CostSpineService(session)


def _str_to_float(value: object) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0.

    Mirrors the service-layer helper so the Monte Carlo endpoint can read the
    Decimal-as-string ``planned`` totals returned by the FX-aware aggregator
    without re-importing a private symbol.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


async def _distinct_budget_currencies(
    session: SessionDep,
    project_id: uuid.UUID,
    budget_line_model: type,
    select_fn: object,
) -> set[str]:
    """Return the distinct non-blank ISO currency codes used by a project's budget lines.

    Currency-blending fix: callers use this to decide whether summing across
    lines is safe (one currency) or whether to surface a ``mixed_currency``
    flag (multiple currencies, which may have been blended across missing
    fx_rates). Blank/None currencies are ignored - they are legacy rows
    written before the multi-currency wave and are treated as project base.
    """
    stmt = select_fn(budget_line_model.currency).where(budget_line_model.project_id == project_id).distinct()
    result = await session.execute(stmt)
    return {(row[0] or "").strip().upper() for row in result.all() if (row[0] or "").strip()}


# ── Helper: convert model → response ────────────────────────────────────────


def _snapshot_to_response(snap: object) -> SnapshotResponse:
    """‌⁠‍Convert a CostSnapshot ORM model to a SnapshotResponse."""
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
        earned_amount=getattr(line, "earned_amount", None),
        period_start=line.period_start,  # type: ignore[attr-defined]
        period_end=line.period_end,  # type: ignore[attr-defined]
        currency=line.currency,  # type: ignore[attr-defined]
        overrun_alert_threshold_pct=getattr(line, "overrun_alert_threshold_pct", "0") or "0",
        overrun_alerted_at=getattr(line, "overrun_alerted_at", None),
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
    "/projects/{project_id}/5d/dashboard/",
    response_model=DashboardResponse,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_dashboard(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> DashboardResponse:
    """Get aggregated 5D cost dashboard KPIs for a project."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_dashboard(project_id)


@router.get(
    "/projects/{project_id}/5d/s-curve/",
    response_model=SCurveData,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_s_curve(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> SCurveData:
    """Get S-curve time series data for chart visualisation."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_s_curve(project_id)


@router.get(
    "/projects/{project_id}/5d/cash-flow/",
    response_model=CashFlowData,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_cash_flow(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> CashFlowData:
    """Get monthly cash flow data for chart display."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_cash_flow(project_id)


# ── Budget ───────────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/5d/budget/",
    response_model=BudgetSummary,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_budget_summary(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> BudgetSummary:
    """Get budget summary grouped by cost category."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_budget_summary(project_id)


@router.get(
    "/projects/{project_id}/5d/budget-lines/",
    response_model=list[BudgetLineResponse],
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def list_budget_lines(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    category: str | None = Query(default=None, description="Filter by cost category"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: CostModelService = Depends(_get_service),
) -> list[BudgetLineResponse]:
    """List detailed budget lines for a project."""
    await verify_project_access(project_id, user_id, session)
    lines, _ = await service.list_budget_lines(project_id, category=category, offset=offset, limit=limit)
    return [_budget_line_to_response(line) for line in lines]


@router.post(
    "/projects/{project_id}/5d/budget-lines/",
    response_model=BudgetLineResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def create_budget_line(
    project_id: uuid.UUID,
    data: BudgetLineCreate,
    _user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> BudgetLineResponse:
    """Create a new budget line for a project."""
    await verify_project_access(project_id, _user_id, session)
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
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> BudgetLineResponse:
    """Update a budget line (committed, actual, forecast amounts, etc.)."""
    existing = await service.budget_repo.get_by_id(line_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget line not found")
    await verify_project_access(existing.project_id, user_id, session)
    line = await service.update_budget_line(line_id, data)
    return _budget_line_to_response(line)


@router.patch(
    "/5d/budget-lines/{line_id}/overrun-alert-threshold",
    response_model=BudgetLineResponse,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def set_overrun_alert_threshold(
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    threshold: float = Query(
        ...,
        ge=0.0,
        le=100.0,
        description="Percentage above planned that arms a cost-overrun alert (0 disables).",
    ),
    service: CostModelService = Depends(_get_service),
) -> BudgetLineResponse:
    """Set the cost-overrun alert threshold on a budget line (Gap D).

    ``threshold`` is a percentage in ``[0, 100]``; ``0`` disables alerting on
    the line. When the line's ``actual_amount`` later breaches
    ``planned_amount * (1 + threshold / 100)``, the cost-overrun subscriber
    notifies the project owner (subject to a 24h cooldown).
    """
    existing = await service.budget_repo.get_by_id(line_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget line not found")
    await verify_project_access(existing.project_id, user_id, session)
    line = await service.set_overrun_alert_threshold(line_id, threshold)
    return _budget_line_to_response(line)


@router.delete(
    "/5d/budget-lines/{line_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def delete_budget_line(
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> None:
    """Delete a budget line."""
    existing = await service.budget_repo.get_by_id(line_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget line not found")
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_budget_line(line_id)


# ── Budget Generation ────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/generate-budget/",
    response_model=list[BudgetLineResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def generate_budget(
    project_id: uuid.UUID,
    _user_id: CurrentUserId,
    session: SessionDep,
    body: dict,
    service: CostModelService = Depends(_get_service),
) -> list[BudgetLineResponse]:
    """Auto-generate budget lines from BOQ positions.

    The request body should look like ``{"boq_id": "<uuid>"}``. If `boq_id` is
    omitted, the project's first/largest BOQ is used automatically.
    """
    await verify_project_access(project_id, _user_id, session)
    raw_boq_id = body.get("boq_id") if isinstance(body, dict) else None
    if raw_boq_id:
        try:
            boq_id = uuid.UUID(str(raw_boq_id))
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid boq_id: {e}",
            )
    else:
        # Auto-pick: project's first BOQ (most-positions wins)
        picked = await service.pick_default_boq(project_id)
        if picked is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No BOQ found for this project - create one first.",
            )
        boq_id = picked

    lines = await service.generate_budget_from_boq(project_id, boq_id)
    return [_budget_line_to_response(line) for line in lines]


# ── Snapshots (EVM) ─────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/snapshots/",
    response_model=SnapshotResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def create_snapshot(
    project_id: uuid.UUID,
    data: SnapshotCreate,
    _user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> SnapshotResponse:
    """Create a new EVM cost snapshot for a project."""
    await verify_project_access(project_id, _user_id, session)
    data.project_id = project_id
    snapshot = await service.create_snapshot(data)
    return _snapshot_to_response(snapshot)


@router.get(
    "/projects/{project_id}/5d/snapshots/",
    response_model=list[SnapshotResponse],
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def list_snapshots(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    period_from: str | None = Query(default=None, description="Start period (YYYY-MM)"),
    period_to: str | None = Query(default=None, description="End period (YYYY-MM)"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: CostModelService = Depends(_get_service),
) -> list[SnapshotResponse]:
    """List EVM snapshots for a project, optionally filtered by period range."""
    await verify_project_access(project_id, user_id, session)
    snapshots, _ = await service.list_snapshots(
        project_id,
        period_from=period_from,
        period_to=period_to,
        offset=offset,
        limit=limit,
    )
    return [_snapshot_to_response(snap) for snap in snapshots]


@router.patch(
    "/5d/snapshots/{snapshot_id}",
    response_model=SnapshotResponse,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def update_snapshot(
    snapshot_id: uuid.UUID,
    data: SnapshotUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> SnapshotResponse:
    """Update an EVM cost snapshot (notes, values, etc.)."""
    existing = await service.get_snapshot(snapshot_id)
    await verify_project_access(existing.project_id, user_id, session)
    snapshot = await service.update_snapshot(snapshot_id, data)
    return _snapshot_to_response(snapshot)


@router.delete(
    "/projects/{project_id}/5d/snapshots/{snapshot_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def delete_snapshot(
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> None:
    """Delete an EVM cost snapshot."""
    await verify_project_access(project_id, user_id, session)
    snapshot = await service.get_snapshot(snapshot_id)
    if str(snapshot.project_id) != str(project_id):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    await service.delete_snapshot(snapshot_id)


# ── EVM (Earned Value Management) ───────────────────────────────────────────


@router.get(
    "/projects/{project_id}/5d/evm/",
    response_model=EVMResponse,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_evm(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> EVMResponse:
    """Calculate full EVM metrics from schedule progress and budget data.

    Returns BAC, PV, EV, AC, SV, CV, SPI, CPI, EAC, ETC, VAC, TCPI
    computed by linking budget lines to schedule activities.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.calculate_evm(project_id)


# ── What-If Scenarios ──────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/what-if/",
    response_model=WhatIfResult,
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def create_what_if_scenario(
    project_id: uuid.UUID,
    data: WhatIfAdjustments,
    _user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> WhatIfResult:
    """Create a what-if cost scenario by applying percentage adjustments.

    Clones current budget state, applies material/labor/duration adjustments,
    and returns the impact on EAC. Also creates a snapshot for the scenario.
    """
    await verify_project_access(project_id, _user_id, session)
    return await service.create_what_if_scenario(project_id, data)


# ── Cash Flow Generation ────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/generate-cash-flow/",
    response_model=list[CashFlowResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def generate_cash_flow(
    project_id: uuid.UUID,
    _user_id: CurrentUserId,
    session: SessionDep,
    service: CostModelService = Depends(_get_service),
) -> list[CashFlowResponse]:
    """Generate cash flow entries by spreading budget across schedule."""
    await verify_project_access(project_id, _user_id, session)
    entries = await service.generate_cash_flow_from_schedule(project_id)
    return [_cash_flow_to_response(entry) for entry in entries]


# ── Monte Carlo Cost Simulation ──────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/5d/monte-carlo/",
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def run_monte_carlo(
    project_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    iterations: int = Query(default=1000, ge=100, le=5000),
    service: CostModelService = Depends(_get_service),
) -> dict:
    """Run Monte Carlo cost risk simulation.

    Generates N random cost outcomes based on category-level uncertainty,
    then returns percentile estimates (P50, P80, P95) and a histogram.
    """
    await verify_project_access(project_id, _user_id, session)
    import random

    from sqlalchemy import select

    from app.modules.costmodel.models import BudgetLine

    # ── Money correctness (currency-blending fix) ────────────────────────────
    # Previously this aggregated planned_amount with a raw SQL
    # ``func.sum(cast(BudgetLine.planned_amount, Float))`` grouped by category
    # only - it ignored each line's ``currency`` and never converted through
    # the project's fx_rates. For any multi-currency project that silently
    # summed e.g. USD + EUR + JPY into one scalar BAC, so every derived
    # percentile/mean/std_dev/histogram was computed on a meaningless mixed-
    # currency number. We now reuse the FX-aware ``aggregate_by_category``
    # (same helper the dashboard / budget summary / EVM already use), which
    # converts every line to the project base currency before summing, and we
    # label the whole simulation with that base ISO currency.
    rows = await service.budget_repo.aggregate_by_category(project_id)
    categories = [{"category": r["category"], "planned": _str_to_float(r["planned"])} for r in rows]

    # Resolve the project base currency to LABEL the result. Falls back to ""
    # (unknown) rather than hardcoding "EUR" - the UI renders a bare number
    # for a blank/invalid code instead of mislabelling foreign money as EUR.
    currency = await service._get_project_currency(project_id)

    # Guard: if budget lines carry more than one distinct ISO currency we may
    # have converted across missing fx_rates (foreign lines with no rate are
    # kept in their own units by the aggregator), so surface a mixed_currency
    # flag instead of pretending the scalar is clean. A single distinct
    # currency (or only-base/blank rows) is treated as clean.
    line_ccys = await _distinct_budget_currencies(session, project_id, BudgetLine, select)
    mixed_currency = len(line_ccys) > 1

    bac = sum(c["planned"] for c in categories)
    if bac <= 0:
        from fastapi import HTTPException

        raise HTTPException(400, detail="No budget data. Generate budget from BOQ first.")

    # Uncertainty by category (standard deviation as fraction of planned)
    uncertainty = {
        "material": 0.12,
        "labor": 0.08,
        "equipment": 0.10,
        "subcontractor": 0.15,
        "overhead": 0.05,
        "contingency": 0.20,
    }

    results: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for cat in categories:
            std = uncertainty.get(cat["category"], 0.10)
            simulated = random.gauss(cat["planned"], cat["planned"] * std)
            total += max(0, simulated)
        results.append(round(total, 2))

    results.sort()
    n = len(results)
    mean = sum(results) / n

    # Histogram (10 bins)
    mn, mx = results[0], results[-1]
    step = (mx - mn) / 10 if mx > mn else 1
    histogram = []
    for i in range(10):
        lo = mn + i * step
        hi = mn + (i + 1) * step
        if i < 9:
            count = sum(1 for v in results if lo <= v < hi)
        else:
            count = sum(1 for v in results if lo <= v <= hi)
        histogram.append({"from": round(lo, 0), "to": round(hi, 0), "count": count})

    return {
        "iterations": n,
        "bac": round(bac, 2),
        "min": results[0],
        "max": results[-1],
        "mean": round(mean, 2),
        "p50": results[min(int(n * 0.50), n - 1)],
        "p80": results[min(int(n * 0.80), n - 1)],
        "p95": results[min(int(n * 0.95), n - 1)],
        "std_dev": round((sum((r - mean) ** 2 for r in results) / n) ** 0.5, 2),
        "histogram": histogram,
        # Currency-blending fix: label the simulation with the project's base
        # ISO currency (blank when unknown - never hardcoded EUR) and flag when
        # the underlying budget lines mixed currencies so the client can warn.
        "currency": currency,
        "mixed_currency": mixed_currency,
    }


# ── Project Intelligence (RFC 25) ───────────────────────────────────────────


@router.get(
    "/variance/",
    response_model=VarianceResponse,
    summary="Budget variance KPI (RFC 25)",
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_variance(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(..., description="Project scope"),
    service: CostModelService = Depends(_get_service),
) -> VarianceResponse:
    """Return budget-variance KPI for the Estimation Dashboard."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_variance(project_id)


# ── Cost Spine: control accounts ──────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/spine/accounts/",
    response_model=list[ControlAccountResponse],
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def list_control_accounts(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> list[ControlAccountResponse]:
    """List the project's control accounts, tree-ordered."""
    await verify_project_access(project_id, user_id, session)
    return await service.list_accounts(project_id)


@router.post(
    "/projects/{project_id}/spine/accounts/",
    response_model=ControlAccountResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def create_control_account(
    project_id: uuid.UUID,
    data: ControlAccountCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> ControlAccountResponse:
    """Create a control account under a project."""
    await verify_project_access(project_id, user_id, session)
    data.project_id = project_id
    return await service.create_account(data)


@router.patch(
    "/spine/accounts/{account_id}",
    response_model=ControlAccountResponse,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def update_control_account(
    account_id: uuid.UUID,
    data: ControlAccountUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> ControlAccountResponse:
    """Update a control account (resolves the row, then verifies project access)."""
    existing = await service.account_repo.get_by_id(account_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control account not found")
    await verify_project_access(existing.project_id, user_id, session)
    return await service.update_account(account_id, data)


@router.delete(
    "/spine/accounts/{account_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("costmodel.manage"))],
)
async def delete_control_account(
    account_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> None:
    """Delete a control account (409 when cost lines still reference it)."""
    existing = await service.account_repo.get_by_id(account_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control account not found")
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_account(account_id)


# ── Cost Spine: cost lines ────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/spine/lines/",
    response_model=list[CostLineResponse],
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def list_cost_lines(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    control_account_id: uuid.UUID | None = Query(default=None, description="Filter by control account"),
    line_status: str | None = Query(default=None, alias="status", description="Filter by cost-line status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: CostSpineService = Depends(_get_spine_service),
) -> list[CostLineResponse]:
    """List cost lines for a project, optionally filtered by account/status."""
    await verify_project_access(project_id, user_id, session)
    return await service.list_lines(
        project_id,
        control_account_id=control_account_id,
        status=line_status,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/projects/{project_id}/spine/lines/",
    response_model=CostLineResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def create_cost_line(
    project_id: uuid.UUID,
    data: CostLineCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> CostLineResponse:
    """Create a cost line under a project."""
    await verify_project_access(project_id, user_id, session)
    data.project_id = project_id
    return await service.create_line(data)


@router.patch(
    "/spine/lines/{line_id}",
    response_model=CostLineResponse,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def update_cost_line(
    line_id: uuid.UUID,
    data: CostLineUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> CostLineResponse:
    """Update a cost line (resolves the row, then verifies project access)."""
    existing = await service.line_repo.get_by_id(line_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
    await verify_project_access(existing.project_id, user_id, session)
    return await service.update_line(line_id, data)


@router.delete(
    "/spine/lines/{line_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("costmodel.manage"))],
)
async def delete_cost_line(
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> None:
    """Delete a cost line (409 with linked counts when references remain)."""
    existing = await service.line_repo.get_by_id(line_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_line(line_id)


@router.get(
    "/spine/lines/{line_id}/rollup/",
    response_model=CostLineRollupResponse,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_cost_line_rollup(
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> CostLineRollupResponse:
    """Return the money rollup for a single cost line."""
    existing = await service.line_repo.get_by_id(line_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
    await verify_project_access(existing.project_id, user_id, session)
    return await service.rollup_for_line(line_id)


@router.post(
    "/spine/lines/{line_id}/link/",
    response_model=CostLineRollupResponse,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def link_cost_line_target(
    line_id: uuid.UUID,
    data: SpineLinkRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> CostLineRollupResponse:
    """Link a downstream entity (BOQ position / budget / PO item / contract line / RFQ)."""
    existing = await service.line_repo.get_by_id(line_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
    await verify_project_access(existing.project_id, user_id, session)
    return await service.link_target(line_id, data.target_type, data.target_id)


# ── Cost Spine: generation + project rollup ───────────────────────────────────


@router.post(
    "/projects/{project_id}/spine/generate-from-boq/",
    response_model=SpineGenerationResult,
    dependencies=[Depends(RequirePermission("costmodel.write"))],
)
async def generate_spine_from_boq(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    body: dict | None = None,
    service: CostSpineService = Depends(_get_spine_service),
) -> SpineGenerationResult:
    """Generate the cost spine from a BOQ (idempotent).

    Body may contain ``{"boq_id": "<uuid>"}``; when omitted the project's
    most-recent BOQ is used.
    """
    await verify_project_access(project_id, user_id, session)
    boq_id: uuid.UUID | None = None
    raw_boq_id = body.get("boq_id") if isinstance(body, dict) else None
    if raw_boq_id:
        try:
            boq_id = uuid.UUID(str(raw_boq_id))
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid boq_id: {e}",
            )
    return await service.generate_from_boq(project_id, boq_id)


@router.get(
    "/projects/{project_id}/spine/rollup/",
    response_model=SpineRollupResponse,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_spine_rollup(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CostSpineService = Depends(_get_spine_service),
) -> SpineRollupResponse:
    """Return the project-wide Cost Spine rollup (accounts + lines + totals)."""
    await verify_project_access(project_id, user_id, session)
    return await service.rollup_for_project(project_id)
