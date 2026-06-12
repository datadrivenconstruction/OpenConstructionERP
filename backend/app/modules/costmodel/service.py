"""‌⁠‍5D Cost Model service - business logic for EVM, budgets, and cash flow.

Stateless service layer.  Handles:
- EVM snapshot creation and S-curve data
- Dashboard KPIs aggregation
- Budget generation from BOQ positions
- Cash flow generation from budget schedule
- Event publishing for inter-module communication
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.costmodel.models import (
    BudgetLine,
    CashFlow,
    ControlAccount,
    CostLine,
    CostSnapshot,
)
from app.modules.costmodel.repository import (
    BudgetLineRepository,
    CashFlowRepository,
    ControlAccountRepository,
    CostLineRepository,
    CostSpineRepository,
    SnapshotRepository,
    _amount_in_base,
)
from app.modules.costmodel.schemas import (
    BudgetCategoryRow,
    BudgetLineCreate,
    BudgetLineUpdate,
    BudgetSummary,
    CashFlowCreate,
    CashFlowData,
    CashFlowPeriod,
    ControlAccountCreate,
    ControlAccountResponse,
    ControlAccountUpdate,
    CostLineCreate,
    CostLineLinks,
    CostLineResponse,
    CostLineRollupResponse,
    CostLineUpdate,
    DashboardResponse,
    EVMResponse,
    SCurveData,
    SCurvePeriod,
    SnapshotCreate,
    SnapshotUpdate,
    SpineGenerationResult,
    SpineRollupResponse,
    WhatIfAdjustments,
    WhatIfResult,
)

_logger_ev = logging.getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


logger = logging.getLogger(__name__)

# Allowed cost categories for an actual-cost posting (Gap B). Mirrors the
# BudgetLine.category doc plus the what-if/dashboard category vocabulary. An
# empty / None category is always allowed (the "uncategorised" sentinel).
_ACTUAL_COST_CATEGORIES = frozenset({"material", "labor", "equipment", "subcontractor", "overhead", "contingency"})

# metadata.kind marker for budget lines auto-maintained by actual-cost postings.
_ACTUAL_POSTING_MARKER = "actual_posting_auto"


def _str_to_float(value: str | None) -> float:
    """‌⁠‍Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _str_to_decimal(value: str | None) -> Decimal:
    """Convert a Decimal-as-string aggregate to Decimal, defaulting to 0.

    Keeps money exact (v3 §10): the repository emits FX-converted sums as
    ``str(Decimal)``, so we parse them straight back to Decimal instead of
    going through float and losing precision.
    """
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return Decimal("0")


def _safe_divide(numerator: float, denominator: float) -> float:
    """‌⁠‍Safely divide two floats, returning 0.0 on zero denominator."""
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _parse_iso_date(value: str | None) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of an ISO date/datetime string.

    Returns ``None`` when ``value`` is empty or unparseable, so callers can
    fall back gracefully instead of raising on dirty data.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _phase_fraction(start: date, end: date, as_of: date) -> Decimal:
    """Fraction of a planned window [start, end] elapsed by ``as_of``.

    Linear distribution over the inclusive-exclusive day span. Clamped to
    ``[0, 1]``. A zero/negative span (start >= end, e.g. a milestone) counts
    as fully earned once ``as_of`` reaches ``start``.

    Args:
        start: Window planned start date.
        end: Window planned finish date.
        as_of: The valuation date (the EVM "data date" / today).

    Returns:
        A Decimal in ``[0, 1]``.
    """
    total_days = (end - start).days
    if total_days <= 0:
        return Decimal("1") if as_of >= start else Decimal("0")
    elapsed_days = (as_of - start).days
    if elapsed_days <= 0:
        return Decimal("0")
    if elapsed_days >= total_days:
        return Decimal("1")
    return Decimal(elapsed_days) / Decimal(total_days)


# Fallback chain a budget line walks to find the planned window over which its
# amount is time-phased. See :meth:`CostModelService._time_phased_pv`.
PVSource = str  # "activity" | "line_period" | "project_period" | "approximation"


def _variance_pct(planned: float, forecast: float) -> float:
    """Calculate variance percentage: (planned - forecast) / planned * 100."""
    if planned == 0.0:
        return 0.0
    return round((planned - forecast) / planned * 100.0, 2)


# ── Cost-overrun alerts (Gap D) ────────────────────────────────────────────────

# Cooldown between two overrun alerts for the same budget line (design §"Idempotent").
_OVERRUN_COOLDOWN = timedelta(hours=24)


def is_budget_line_overrun(planned: object, actual: object, threshold_pct: object) -> bool:
    """Return whether ``actual`` has breached the overrun threshold of ``planned``.

    Pure decision function (no I/O) so the overrun rule is unit-testable in
    isolation and reused identically by the subscriber. Money/percentage inputs
    are the Decimal-as-string column values; they are parsed defensively.

    The breach condition is ``actual >= planned * (1 + threshold_pct / 100)``.
    Returns ``False`` when:
        * the threshold is ``<= 0`` (alerting disabled - '0' is the sentinel);
        * ``planned`` is ``<= 0`` (no baseline to measure an overrun against);
        * any input fails to parse as a finite number.

    All arithmetic is Decimal so a million-currency baseline does not drift.
    """

    def _dec(value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            d = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return d if d.is_finite() else None

    threshold = _dec(threshold_pct)
    if threshold is None or threshold <= 0:
        return False
    planned_d = _dec(planned)
    if planned_d is None or planned_d <= 0:
        return False
    actual_d = _dec(actual)
    if actual_d is None:
        return False

    limit = planned_d * (Decimal("1") + threshold / Decimal("100"))
    return actual_d >= limit


class CostModelService:
    """Business logic for 5D Cost Model operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.snapshot_repo = SnapshotRepository(session)
        self.budget_repo = BudgetLineRepository(session)
        self.cashflow_repo = CashFlowRepository(session)

    async def _get_project_currency(self, project_id: uuid.UUID) -> str:
        """Return the project's configured currency.

        Currency is strictly data-driven - it comes from the project record
        and nowhere else. When the project has no currency set (or the lookup
        fails) we return an empty string rather than fabricating a default;
        the UI is responsible for rendering a currency-less number instead of
        silently mislabelling, e.g., USD costs as EUR.
        """
        try:
            from app.modules.projects.repository import ProjectRepository

            repo = ProjectRepository(self.session)
            project = await repo.get_by_id(project_id)
            return project.currency if project and project.currency else ""
        except Exception:
            return ""

    # ── Snapshot operations ────────────────────────────────────────────────

    async def create_snapshot(self, data: SnapshotCreate) -> CostSnapshot:
        """Create a monthly EVM snapshot.

        Computes SPI and CPI from the provided planned/earned/actual values
        if they are not explicitly set.

        R5 audit (May 2026): ``(project_id, period)`` must be unique.
        Pre-audit two snapshots for the same period silently coexisted -
        ``get_latest_for_project`` then picked one arbitrarily and EVM
        rollups flapped between them. The DB-level unique index added in
        migration v3108 is the belt to this in-process suspenders.

        Args:
            data: Snapshot creation payload.

        Returns:
            The newly created snapshot.

        Raises:
            HTTPException: 409 if a snapshot already exists for
                ``(project_id, period)``.
        """
        # ── Duplicate-period guard (R5 audit) ────────────────────────────
        existing = await self.snapshot_repo.get_for_project_period(data.project_id, data.period)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Snapshot for period {data.period} already exists for "
                    "this project. Update the existing snapshot instead "
                    "(PATCH /5d/snapshots/{snapshot_id})."
                ),
            )

        spi = data.spi
        cpi = data.cpi

        # Auto-compute indices if not provided (left at default 0).
        # v3 §10 - money fields are Decimal; cast to float at this
        # boundary because SPI/CPI are unitless ratios stored as float.
        if spi == 0.0 and float(data.planned_cost) > 0.0:
            spi = round(
                _safe_divide(float(data.earned_value), float(data.planned_cost)),
                4,
            )
        if cpi == 0.0 and float(data.actual_cost) > 0.0:
            cpi = round(
                _safe_divide(float(data.earned_value), float(data.actual_cost)),
                4,
            )

        snapshot = CostSnapshot(
            project_id=data.project_id,
            period=data.period,
            planned_cost=str(data.planned_cost),
            earned_value=str(data.earned_value),
            actual_cost=str(data.actual_cost),
            forecast_eac=str(data.forecast_eac),
            spi=str(spi),
            cpi=str(cpi),
            notes=data.notes,
            metadata_=data.metadata,
        )
        snapshot = await self.snapshot_repo.create(snapshot)

        await _safe_publish(
            "costmodel.snapshot.created",
            {
                "snapshot_id": str(snapshot.id),
                "project_id": str(data.project_id),
                "period": data.period,
            },
            source_module="oe_costmodel",
        )

        logger.info(
            "EVM snapshot created: project=%s period=%s",
            data.project_id,
            data.period,
        )
        return snapshot

    async def get_snapshot(self, snapshot_id: uuid.UUID) -> CostSnapshot:
        """Get snapshot by ID. Raises 404 if not found."""
        snapshot = await self.snapshot_repo.get_by_id(snapshot_id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Snapshot not found",
            )
        return snapshot

    async def list_snapshots(
        self,
        project_id: uuid.UUID,
        *,
        period_from: str | None = None,
        period_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CostSnapshot], int]:
        """List EVM snapshots for a project with optional period range."""
        return await self.snapshot_repo.list_for_project(
            project_id,
            period_from=period_from,
            period_to=period_to,
            offset=offset,
            limit=limit,
        )

    async def update_snapshot(self, snapshot_id: uuid.UUID, data: SnapshotUpdate) -> CostSnapshot:
        """Update an EVM snapshot.

        Args:
            snapshot_id: Target snapshot identifier.
            data: Partial update payload.

        Returns:
            Updated snapshot.
        """
        await self.get_snapshot(snapshot_id)

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        for key in (
            "planned_cost",
            "earned_value",
            "actual_cost",
            "forecast_eac",
            "spi",
            "cpi",
        ):
            if key in fields:
                fields[key] = str(fields[key])

        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.snapshot_repo.update_fields(snapshot_id, **fields)

        updated = await self.snapshot_repo.get_by_id(snapshot_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Snapshot not found after update",
            )
        return updated

    async def delete_snapshot(self, snapshot_id: uuid.UUID) -> None:
        """Delete an EVM cost snapshot. Raises 404 if not found.

        Emits a ``costmodel.snapshot.deleted`` event so downstream
        aggregates (portfolio dashboards, S-curve caches) can invalidate.
        """
        snapshot = await self.snapshot_repo.get_by_id(snapshot_id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Snapshot not found",
            )

        project_id = str(snapshot.project_id)
        period = snapshot.period
        await self.snapshot_repo.delete(snapshot_id)

        await _safe_publish(
            "costmodel.snapshot.deleted",
            {
                "snapshot_id": str(snapshot_id),
                "project_id": project_id,
                "period": period,
            },
            source_module="oe_costmodel",
        )

        logger.info("EVM snapshot deleted: %s", snapshot_id)

    # ── Dashboard ──────────────────────────────────────────────────────────

    async def get_dashboard(self, project_id: uuid.UUID) -> DashboardResponse:
        """Aggregate all budget lines into summary KPIs.

        Computes total budget, committed, actual, forecast, variance,
        and pulls SPI/CPI from the latest EVM snapshot.

        Args:
            project_id: Target project.

        Returns:
            DashboardResponse with aggregated KPIs.
        """
        aggregates = await self.budget_repo.aggregate_by_project(project_id)

        # Money stays Decimal end-to-end (v3 §10). The repository returns the
        # FX-converted sums as Decimal-as-string; parse straight back to
        # Decimal rather than round-tripping through float, which would
        # reintroduce binary-float imprecision into the dashboard totals.
        total_budget = _str_to_decimal(aggregates["total_planned"])
        total_committed = _str_to_decimal(aggregates["total_committed"])
        total_actual = _str_to_decimal(aggregates["total_actual"])
        total_forecast = _str_to_decimal(aggregates["total_forecast"])
        variance = total_budget - total_forecast

        # Detect whether the budget lines span more than one currency. When
        # they do, the repo's per-line FX conversion may have blended an
        # unconverted foreign amount (missing fx_rate) into the totals, so
        # surface a flag the UI can warn on instead of trusting the sum.
        mixed_currency = len(await self.budget_repo.distinct_currencies(project_id)) > 1

        # Get SPI and CPI from latest snapshot
        spi = 0.0
        cpi = 0.0
        latest = await self.snapshot_repo.get_latest_for_project(project_id)
        if latest is not None:
            spi = _str_to_float(latest.spi)
            cpi = _str_to_float(latest.cpi)

        budget_status = "on_budget" if variance >= 0 else "over_budget"

        # Ratios stay float; compute variance % from the float view.
        budget_f = float(total_budget)
        variance_pct = _variance_pct(budget_f, float(total_forecast)) if budget_f > 0 else 0.0

        return DashboardResponse(
            total_budget=total_budget.quantize(Decimal("0.01")),
            total_committed=total_committed.quantize(Decimal("0.01")),
            total_actual=total_actual.quantize(Decimal("0.01")),
            total_forecast=round(float(total_forecast), 2),
            variance=round(float(variance), 2),
            variance_pct=round(variance_pct, 2),
            spi=round(spi, 4),
            cpi=round(cpi, 4),
            status=budget_status,
            currency=await self._get_project_currency(project_id),
            mixed_currency=mixed_currency,
        )

    # ── S-Curve ────────────────────────────────────────────────────────────

    async def get_s_curve(self, project_id: uuid.UUID) -> SCurveData:
        """Build S-curve time series from EVM snapshots.

        Each snapshot stores the standard EVM measures BCWS/BCWP/ACWP
        (planned_cost / earned_value / actual_cost). By definition these are
        *cumulative-to-date* values, and every other consumer in this module
        (dashboard, EVM, what-if) treats them as absolute totals. The S-curve
        therefore plots the snapshot values directly - re-summing them across
        periods (the previous behaviour) double-counted and produced curves
        that climbed far past BAC.

        Snapshots are returned ``period`` ascending by the repository, so the
        series is already chronologically ordered.

        Args:
            project_id: Target project.

        Returns:
            SCurveData with list of period data points.
        """
        snapshots, _ = await self.snapshot_repo.list_for_project(project_id, limit=1000)

        periods: list[SCurvePeriod] = []
        for snap in snapshots:
            periods.append(
                SCurvePeriod(
                    period=snap.period,
                    planned=round(_str_to_float(snap.planned_cost), 2),
                    earned=round(_str_to_float(snap.earned_value), 2),
                    actual=round(_str_to_float(snap.actual_cost), 2),
                )
            )

        # Fallback: if no snapshots, build S-curve from cash flow data
        if not periods:
            cash_flows, _ = await self.cashflow_repo.list_for_project(project_id)
            seen: set[str] = set()
            for cf in cash_flows:
                if cf.period in seen:
                    continue
                seen.add(cf.period)
                periods.append(
                    SCurvePeriod(
                        period=cf.period,
                        planned=round(_str_to_float(cf.cumulative_planned), 2),
                        earned=0.0,
                        actual=round(_str_to_float(cf.cumulative_actual), 2),
                    )
                )

        return SCurveData(periods=periods)

    # ── Cash Flow ──────────────────────────────────────────────────────────

    async def get_cash_flow(self, project_id: uuid.UUID) -> CashFlowData:
        """Build monthly cash flow data from cash flow entries.

        Args:
            project_id: Target project.

        Returns:
            CashFlowData with list of period data points.
        """
        entries, _ = await self.cashflow_repo.list_for_project(project_id, limit=1000)

        periods: list[CashFlowPeriod] = []
        for entry in entries:
            inflow = _str_to_float(entry.actual_inflow) or _str_to_float(entry.planned_inflow)
            outflow = _str_to_float(entry.actual_outflow) or _str_to_float(entry.planned_outflow)

            periods.append(
                CashFlowPeriod(
                    period=entry.period,
                    inflow=round(inflow, 2),
                    outflow=round(outflow, 2),
                    cumulative_planned=round(_str_to_float(entry.cumulative_planned), 2),
                    cumulative_actual=round(_str_to_float(entry.cumulative_actual), 2),
                )
            )

        return CashFlowData(periods=periods)

    async def create_cash_flow_entry(self, data: CashFlowCreate) -> CashFlow:
        """Create a manual cash flow entry.

        Args:
            data: Cash flow creation payload.

        Returns:
            The newly created cash flow entry.
        """
        entry = CashFlow(
            project_id=data.project_id,
            period=data.period,
            category=data.category,
            planned_inflow=str(data.planned_inflow),
            planned_outflow=str(data.planned_outflow),
            actual_inflow=str(data.actual_inflow),
            actual_outflow=str(data.actual_outflow),
            cumulative_planned=str(data.cumulative_planned),
            cumulative_actual=str(data.cumulative_actual),
            metadata_=data.metadata,
        )
        entry = await self.cashflow_repo.create(entry)

        await _safe_publish(
            "costmodel.cashflow.created",
            {
                "entry_id": str(entry.id),
                "project_id": str(data.project_id),
                "period": data.period,
            },
            source_module="oe_costmodel",
        )

        logger.info(
            "Cash flow entry created: project=%s period=%s",
            data.project_id,
            data.period,
        )
        return entry

    # ── Budget operations ──────────────────────────────────────────────────

    async def get_budget_summary(self, project_id: uuid.UUID) -> BudgetSummary:
        """Group budget lines by category and compute per-category totals.

        Args:
            project_id: Target project.

        Returns:
            BudgetSummary with per-category breakdown.
        """
        rows = await self.budget_repo.aggregate_by_category(project_id)

        categories: list[BudgetCategoryRow] = []
        for row in rows:
            planned = _str_to_float(row["planned"])
            committed = _str_to_float(row["committed"])
            actual = _str_to_float(row["actual"])
            forecast = _str_to_float(row["forecast"])

            categories.append(
                BudgetCategoryRow(
                    category=row["category"],
                    planned=round(planned, 2),
                    committed=round(committed, 2),
                    actual=round(actual, 2),
                    forecast=round(forecast, 2),
                    variance=round(planned - forecast, 2),
                    variance_pct=_variance_pct(planned, forecast),
                )
            )

        return BudgetSummary(categories=categories)

    async def list_budget_lines(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BudgetLine], int]:
        """List detailed budget lines for a project."""
        return await self.budget_repo.list_for_project(project_id, category=category, offset=offset, limit=limit)

    async def create_budget_line(self, data: BudgetLineCreate) -> BudgetLine:
        """Create a single budget line.

        Args:
            data: Budget line creation payload.

        Returns:
            The newly created budget line.
        """
        line = BudgetLine(
            project_id=data.project_id,
            boq_position_id=data.boq_position_id,
            activity_id=data.activity_id,
            category=data.category,
            description=data.description,
            planned_amount=str(data.planned_amount),
            committed_amount=str(data.committed_amount),
            actual_amount=str(data.actual_amount),
            forecast_amount=str(data.forecast_amount),
            period_start=data.period_start,
            period_end=data.period_end,
            currency=data.currency,
            metadata_=data.metadata,
        )
        line = await self.budget_repo.create(line)

        await _safe_publish(
            "costmodel.budget_line.created",
            {
                "line_id": str(line.id),
                "project_id": str(data.project_id),
                "category": data.category,
            },
            source_module="oe_costmodel",
        )

        logger.info(
            "Budget line created: project=%s category=%s",
            data.project_id,
            data.category,
        )
        return line

    async def update_budget_line(self, line_id: uuid.UUID, data: BudgetLineUpdate) -> BudgetLine:
        """Update committed, actual, forecast or other fields on a budget line.

        Args:
            line_id: Target budget line identifier.
            data: Partial update payload.

        Returns:
            Updated budget line.
        """
        line = await self.budget_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Budget line not found",
            )

        # Capture project_id before update_fields() calls expire_all(),
        # which would invalidate the ORM object and trigger a sync lazy-load
        # (MissingGreenlet) when accessing line.project_id afterwards.
        project_id_str = str(line.project_id)

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        for key in ("planned_amount", "committed_amount", "actual_amount", "forecast_amount"):
            if key in fields:
                fields[key] = str(fields[key])

        # Convert GUID fields to string for storage
        for key in ("boq_position_id", "activity_id"):
            if key in fields and fields[key] is not None:
                fields[key] = fields[key]  # GUID type handles conversion

        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.budget_repo.update_fields(line_id, **fields)

            await _safe_publish(
                "costmodel.budget_line.updated",
                {
                    "line_id": str(line_id),
                    "project_id": project_id_str,
                    "fields": list(fields.keys()),
                },
                source_module="oe_costmodel",
            )

        updated = await self.budget_repo.get_by_id(line_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Budget line not found after update",
            )
        return updated

    async def delete_budget_line(self, line_id: uuid.UUID) -> None:
        """Delete a budget line. Raises 404 if not found."""
        line = await self.budget_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Budget line not found",
            )

        project_id = str(line.project_id)
        await self.budget_repo.delete(line_id)

        await _safe_publish(
            "costmodel.budget_line.deleted",
            {"line_id": str(line_id), "project_id": project_id},
            source_module="oe_costmodel",
        )

        logger.info("Budget line deleted: %s", line_id)

    async def set_overrun_alert_threshold(self, line_id: uuid.UUID, threshold_pct: float) -> BudgetLine:
        """Arm (or disable) the cost-overrun alert threshold on a budget line (Gap D).

        ``threshold_pct`` is a percentage in ``[0, 100]``; ``0`` disables
        alerting. The value is stored as a string (column vocabulary parity with
        the money columns). Re-publishes ``costmodel.budget_line.updated`` so an
        already-overrun line fires its alert the moment a threshold is armed,
        instead of only on the next actual-cost change.

        Args:
            line_id: Target budget line.
            threshold_pct: Percentage above planned that arms an alert.

        Returns:
            The updated budget line.

        Raises:
            HTTPException: 404 when the line is missing; 400 when the percentage
                is out of range or not a finite number.
        """
        line = await self.budget_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget line not found")

        try:
            pct = Decimal(str(threshold_pct))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid threshold: {threshold_pct!r}",
            ) from exc
        if not pct.is_finite() or pct < 0 or pct > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="threshold must be a percentage between 0 and 100.",
            )

        project_id_str = str(line.project_id)
        # Normalise to a plain decimal string ("10", "12.5"); strips any
        # exponent form so the column / partial-index comparison stays simple.
        stored = format(pct.normalize(), "f")

        await self.budget_repo.update_fields(line_id, overrun_alert_threshold_pct=stored)

        await _safe_publish(
            "costmodel.budget_line.updated",
            {
                "line_id": str(line_id),
                "project_id": project_id_str,
                "fields": ["overrun_alert_threshold_pct"],
            },
            source_module="oe_costmodel",
        )

        updated = await self.budget_repo.get_by_id(line_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Budget line not found after update",
            )
        return updated

    # ── EVM Calculations ──────────────────────────────────────────────────

    @staticmethod
    def _time_phased_pv(
        budget_lines: list[BudgetLine],
        *,
        activity_window: dict[str, tuple[date, date]],
        project_period: tuple[date, date] | None,
        as_of: date,
        time_elapsed_pct: float,
    ) -> Decimal:
        """Compute time-phased Planned Value as of ``as_of``.

        ``PV(t) = Σ line_amount × phase_fraction_elapsed_by_t`` where the phase
        fraction is the linear share of each line's planned window that has
        elapsed by ``as_of`` (clamped to ``[0, 1]``). All arithmetic is Decimal
        so a multi-million-currency baseline never drifts; the caller converts
        to float only at the response boundary.

        Per-line window fallback chain (first available wins):
            1. The line's linked schedule ``Activity`` planned window
               (``activity_window[str(line.activity_id)]``).
            2. The line's own ``period_start`` .. ``period_end``.
            3. ``project_period`` - the primary schedule's start..end.
            4. Last resort: the legacy approximation
               ``amount × time_elapsed_pct / 100``. Used only when no usable
               window of any kind exists for that line (e.g. a budget line with
               no activity link, no period, and no project schedule dates).

        Args:
            budget_lines: All budget lines for the project.
            activity_window: Map of activity id (str) to planned (start, end).
            project_period: The project/budget planned (start, end), if known.
            as_of: The valuation/data date.
            time_elapsed_pct: Project-level percent elapsed (0..100), used only
                for the last-resort approximation.

        Returns:
            The summed time-phased Planned Value as a Decimal.
        """
        approx_fraction = Decimal(str(time_elapsed_pct)) / Decimal("100")
        total = Decimal("0")
        for line in budget_lines:
            amount = _str_to_decimal(line.planned_amount)
            if amount == 0:
                continue

            window: tuple[date, date] | None = None
            # Level 1: linked activity planned window.
            if line.activity_id is not None:
                window = activity_window.get(str(line.activity_id))
            # Level 2: the line's own period.
            if window is None:
                line_start = _parse_iso_date(line.period_start)
                line_end = _parse_iso_date(line.period_end)
                if line_start is not None and line_end is not None:
                    window = (line_start, line_end)
            # Level 3: the project/budget period.
            if window is None and project_period is not None:
                window = project_period

            if window is not None:
                fraction = _phase_fraction(window[0], window[1], as_of)
            else:
                # Level 4: legacy approximation (no window available at all).
                fraction = approx_fraction

            total += amount * fraction
        return total

    async def calculate_evm(self, project_id: uuid.UUID) -> EVMResponse:
        """Calculate real Earned Value Management metrics from schedule progress and budget.

        Reads schedule activities for progress percentage and budget lines for planned
        and actual values.  Computes all standard EVM indices.

        Algorithm:
            1. BAC = sum of planned_amount across all budget lines
            2. AC  = sum of actual_amount across all budget lines
            3. PV  = real time-phased Planned Value (see :meth:`_time_phased_pv`):
               each budget line's planned_amount is distributed linearly over a
               planned window and only the fraction elapsed by the data date
               counts toward PV.
            4. schedule_progress% = weighted average of activity progress_pct
               (weighted by planned_amount of linked budget lines)
            5. EV  = BAC * schedule_progress%
            6. Derived indices: SV, CV, SPI, CPI, EAC, ETC, VAC, TCPI

        Planned-Value fallback chain (per budget line, see
        :meth:`_time_phased_pv`):
            1. The line's linked schedule Activity planned window
               (``Activity.start_date`` .. ``Activity.end_date``).
            2. The line's own ``period_start`` .. ``period_end``.
            3. The project/budget period - the primary schedule's
               ``start_date`` .. ``end_date``.
            4. Last resort: the legacy approximation ``amount * time_elapsed%``
               (only when no window of any kind is available).

        SPI guard:
            When PV collapses toward zero (project barely started) we still
            clamp ``pv`` to a minimum of ``1% × BAC`` and ``spi`` to
            ``[0.0, 5.0]`` and set ``spi_capped=True`` so the UI can flag the
            figure as unreliable.

        Args:
            project_id: Target project.

        Returns:
            EVMResponse with all computed EVM metrics.
        """
        from app.modules.schedule.repository import ActivityRepository, ScheduleRepository

        # ── Step 1: Aggregate budget totals ────────────────────────────────
        aggregates = await self.budget_repo.aggregate_by_project(project_id)
        bac = _str_to_float(aggregates["total_planned"])
        ac = _str_to_float(aggregates["total_actual"])

        if bac == 0.0:
            return EVMResponse(
                bac=0.0,
                ac=ac,
                status="unknown",
            )

        # Budget lines are project-scoped; fetch once up front so both the
        # progress weighting and the time-phased PV computation can reuse them.
        budget_lines, _ = await self.budget_repo.list_for_project(project_id, limit=10000)

        # ── Step 2: Read schedule activities for progress ──────────────────
        schedule_repo = ScheduleRepository(self.session)
        schedules, _ = await schedule_repo.list_for_project(project_id, limit=50)

        today = date.today()
        time_elapsed_pct = 0.0
        schedule_progress_pct = 0.0
        # Tracks whether we actually have a usable schedule signal. When False,
        # we surface this to the caller via evm_status="schedule_unknown"
        # instead of silently falling back to a 50 % placeholder - the legacy
        # fallback skewed portfolio-level reports by pretending half-elapsed
        # progress on projects that had no schedule at all.
        schedule_known = False
        # Planned window of the project as a whole - PV fallback level 3.
        project_period: tuple[date, date] | None = None
        # Per-activity planned window keyed by activity id - PV fallback level 1.
        activity_window: dict[str, tuple[date, date]] = {}

        if schedules:
            # Use the first (primary) schedule for time elapsed calculation
            primary_schedule = schedules[0]

            # Compute time_elapsed_pct from schedule dates
            proj_start = _parse_iso_date(primary_schedule.start_date)
            proj_end = _parse_iso_date(primary_schedule.end_date)
            if proj_start is not None and proj_end is not None:
                total_days = (proj_end - proj_start).days
                if total_days > 0:
                    project_period = (proj_start, proj_end)
                    elapsed_days = (today - proj_start).days
                    time_elapsed_pct = max(0.0, min(100.0, (elapsed_days / total_days) * 100.0))
                    schedule_known = True
                else:
                    logger.warning(
                        "Non-positive schedule span on schedule_id=%s (start=%r, end=%r)",
                        getattr(primary_schedule, "id", "<unknown>"),
                        primary_schedule.start_date,
                        primary_schedule.end_date,
                    )
            elif primary_schedule.start_date or primary_schedule.end_date:
                # Log explicitly instead of swallowing silently. Bad schedule
                # dates are a data-quality issue worth surfacing to ops -
                # previously this bug masqueraded as "on track" projects.
                logger.warning(
                    "Unparseable schedule dates on schedule_id=%s (start=%r, end=%r)",
                    getattr(primary_schedule, "id", "<unknown>"),
                    primary_schedule.start_date,
                    primary_schedule.end_date,
                )

            # Compute weighted schedule progress from all activities
            activity_repo = ActivityRepository(self.session)
            total_weighted_progress = 0.0
            total_weight = 0.0

            # Build lookup: budget lines keyed by activity_id (hoisted out of the
            # per-schedule loop - these lines are project-scoped, not schedule-scoped,
            # so fetching once avoids an N+1 query).
            activity_budget: dict[str, float] = {}
            for bl in budget_lines:
                if bl.activity_id is not None:
                    aid = str(bl.activity_id)
                    activity_budget[aid] = activity_budget.get(aid, 0.0) + _str_to_float(bl.planned_amount)

            for schedule in schedules:
                activities, _ = await activity_repo.list_for_schedule(schedule.id, limit=10000)

                for act in activities:
                    act_id = str(act.id)
                    progress = _str_to_float(act.progress_pct)

                    # Capture the activity's planned window for the time-phased
                    # PV computation (fallback level 1).
                    act_start = _parse_iso_date(act.start_date)
                    act_end = _parse_iso_date(act.end_date)
                    if act_start is not None and act_end is not None:
                        activity_window[act_id] = (act_start, act_end)

                    # Weight by the planned budget linked to this activity,
                    # fallback to equal weight if no budget link exists
                    weight = activity_budget.get(act_id, 0.0)
                    if weight == 0.0:
                        # Use equal weight for unlinked activities
                        weight = 1.0

                    total_weighted_progress += weight * progress
                    total_weight += weight

            if total_weight > 0.0:
                schedule_progress_pct = total_weighted_progress / total_weight
        else:
            # No schedule at all - try the latest snapshot as a weak signal,
            # but do NOT fake a 50 % time_elapsed. The old 50 % placeholder
            # silently labelled unscheduled projects as "half-elapsed",
            # which skewed portfolio roll-ups and made at-risk projects look
            # on-track. Instead we leave time_elapsed_pct at 0 and mark
            # evm_status="schedule_unknown" further down so the UI/API caller
            # can tell there is genuinely no schedule data.
            latest = await self.snapshot_repo.get_latest_for_project(project_id)
            if latest is not None:
                pv_snap = _str_to_float(latest.planned_cost)
                ev_snap = _str_to_float(latest.earned_value)
                if pv_snap > 0.0:
                    schedule_progress_pct = (ev_snap / bac) * 100.0

        # ── Step 3: Compute EVM values ─────────────────────────────────────
        # Real time-phased Planned Value: distribute each budget line over its
        # planned window (activity → line period → project period → legacy
        # approximation) and sum only the fraction elapsed by the data date.
        # Decimal math throughout; we clamp to a minimum of 1% × BAC so SPI
        # never explodes toward infinity when the project has barely started.
        raw_pv = float(
            self._time_phased_pv(
                budget_lines,
                activity_window=activity_window,
                project_period=project_period,
                as_of=today,
                time_elapsed_pct=time_elapsed_pct,
            )
        )
        pv_floor = bac * 0.01  # 1% of BAC - prevents divide-by-near-zero
        pv = max(raw_pv, pv_floor)
        ev = bac * (schedule_progress_pct / 100.0)

        sv = ev - pv
        cv = ev - ac
        raw_spi = _safe_divide(ev, pv)
        # Clamp SPI into the [0, 5] band. Anything above 5 is almost certainly
        # the PV proxy being unreliable (project hasn't actually started yet).
        spi_capped = raw_spi > 5.0 or raw_spi < 0.0 or raw_pv < pv_floor
        spi = min(max(raw_spi, 0.0), 5.0)
        cpi = _safe_divide(ev, ac)
        eac = _safe_divide(bac, cpi) if cpi != 0.0 else bac
        etc = max(0.0, eac - ac)
        vac = bac - eac
        # TCPI is mathematically undefined when (BAC - AC) <= 0: the
        # project is at-or-over budget so "work remaining vs cash
        # remaining" has no finite answer. Pre-audit this returned 0.0
        # via _safe_divide, which dashboards mis-rendered as "perfect
        # efficiency required". Surface None so the UI can label N/A.
        tcpi: float | None
        remaining_budget = bac - ac
        if remaining_budget <= 0.0:
            tcpi = None
        else:
            tcpi = (bac - ev) / remaining_budget

        # ── Step 4: Determine project health status ────────────────────────
        # When we have no schedule signal at all, any SPI-based classification
        # is meaningless (see `schedule_known` comment above). Surface a
        # distinct sentinel so dashboards can render "no schedule data" rather
        # than a misleading "on track"/"at risk" badge.
        if not schedule_known:
            evm_status = "schedule_unknown"
        elif spi >= 0.95 and cpi >= 0.95:
            evm_status = "on_track"
        elif spi >= 0.85 and cpi >= 0.85:
            evm_status = "at_risk"
        elif spi > 0.0 or cpi > 0.0:
            evm_status = "critical"
        else:
            evm_status = "unknown"

        logger.info(
            "EVM calculated: project=%s BAC=%.2f PV=%.2f EV=%.2f AC=%.2f SPI=%.4f CPI=%.4f",
            project_id,
            bac,
            pv,
            ev,
            ac,
            spi,
            cpi,
        )

        return EVMResponse(
            bac=round(bac, 2),
            pv=round(pv, 2),
            ev=round(ev, 2),
            ac=round(ac, 2),
            sv=round(sv, 2),
            cv=round(cv, 2),
            spi=round(spi, 4),
            cpi=round(cpi, 4),
            eac=round(eac, 2),
            etc=round(etc, 2),
            vac=round(vac, 2),
            tcpi=round(tcpi, 4) if tcpi is not None else None,
            time_elapsed_pct=round(time_elapsed_pct, 2),
            schedule_progress_pct=round(schedule_progress_pct, 2),
            status=evm_status,
            spi_capped=spi_capped,
        )

    # ── What-If Scenarios ─────────────────────────────────────────────────

    async def create_what_if_scenario(
        self,
        project_id: uuid.UUID,
        adjustments: WhatIfAdjustments,
    ) -> WhatIfResult:
        """Create a what-if scenario by cloning the current budget as a snapshot.

        Applies percentage-based adjustments to material and labor cost categories,
        and optionally adjusts duration impact on forecast.

        Algorithm:
            1. Calculate current EVM as baseline
            2. Compute adjusted BAC by applying category-level adjustments
            3. Compute adjusted EAC using the current CPI against adjusted BAC
            4. Create a snapshot recording the scenario
            5. Return comparison of original vs adjusted values

        Args:
            project_id: Target project.
            adjustments: Scenario name and percentage adjustments.

        Returns:
            WhatIfResult with original and adjusted values plus snapshot reference.
        """
        # ── Step 1: Get current EVM baseline ───────────────────────────────
        evm = await self.calculate_evm(project_id)

        # ── Step 2: Get budget breakdown by category ───────────────────────
        budget_rows = await self.budget_repo.aggregate_by_category(project_id)

        original_bac = evm.bac
        adjusted_bac = 0.0

        for row in budget_rows:
            category = row["category"]
            planned = _str_to_float(row["planned"])

            # Apply category-specific adjustment
            if category == "material":
                factor = 1.0 + (adjustments.material_cost_pct / 100.0)
            elif category == "labor":
                factor = 1.0 + (adjustments.labor_cost_pct / 100.0)
            else:
                factor = 1.0

            adjusted_bac += planned * factor

        # ── Step 3: Apply duration adjustment to indirect/time-dependent costs
        # Duration change affects overhead proportionally
        if adjustments.duration_pct != 0.0:
            duration_factor = 1.0 + (adjustments.duration_pct / 100.0)
            for row in budget_rows:
                if row["category"] in ("overhead", "contingency"):
                    planned = _str_to_float(row["planned"])
                    # Add the delta from duration change (already counted at 1x above)
                    adjusted_bac += planned * (duration_factor - 1.0)

        # ── Step 4: Compute adjusted EAC using current CPI ────────────────
        cpi = evm.cpi if evm.cpi > 0.0 else 1.0
        adjusted_eac = _safe_divide(adjusted_bac, cpi)
        original_eac = evm.eac if evm.eac > 0.0 else original_bac
        delta = adjusted_eac - original_eac
        delta_pct = _variance_pct(original_eac, adjusted_eac) * -1.0 if original_eac > 0.0 else 0.0

        # ── Step 5: Create a snapshot recording the scenario ───────────────
        # Scenarios use a 'wif:<short-id>:YYYY-MM' period so the unique
        # (project_id, period) index added in v3108 cannot reject a
        # legitimate what-if just because the real monthly snapshot also
        # exists for this calendar month.
        from datetime import date

        today = date.today()
        period = f"wif:{uuid.uuid4().hex[:8]}:{today.year:04d}-{today.month:02d}"

        snapshot = CostSnapshot(
            project_id=project_id,
            period=period,
            planned_cost=str(round(adjusted_bac, 2)),
            earned_value=str(round(evm.ev, 2)),
            actual_cost=str(round(evm.ac, 2)),
            forecast_eac=str(round(adjusted_eac, 2)),
            spi=str(round(evm.spi, 4)),
            cpi=str(round(evm.cpi, 4)),
            notes=f"What-if scenario: {adjustments.name}",
            metadata_={
                "scenario": True,
                "scenario_name": adjustments.name,
                "adjustments": {
                    "material_cost_pct": adjustments.material_cost_pct,
                    "labor_cost_pct": adjustments.labor_cost_pct,
                    "duration_pct": adjustments.duration_pct,
                },
                "original_bac": round(original_bac, 2),
                "adjusted_bac": round(adjusted_bac, 2),
            },
        )
        snapshot = await self.snapshot_repo.create(snapshot)

        await _safe_publish(
            "costmodel.whatif.created",
            {
                "snapshot_id": str(snapshot.id),
                "project_id": str(project_id),
                "scenario_name": adjustments.name,
            },
            source_module="oe_costmodel",
        )

        logger.info(
            "What-if scenario created: project=%s name='%s' BAC=%.2f→%.2f EAC=%.2f→%.2f",
            project_id,
            adjustments.name,
            original_bac,
            adjusted_bac,
            original_eac,
            adjusted_eac,
        )

        return WhatIfResult(
            scenario_name=adjustments.name,
            original_bac=round(original_bac, 2),
            adjusted_bac=round(adjusted_bac, 2),
            original_eac=round(original_eac, 2),
            adjusted_eac=round(adjusted_eac, 2),
            delta=round(delta, 2),
            delta_pct=round(delta_pct, 2),
            adjustments_applied={
                "material_cost_pct": adjustments.material_cost_pct,
                "labor_cost_pct": adjustments.labor_cost_pct,
                "duration_pct": adjustments.duration_pct,
            },
            snapshot_id=snapshot.id,
        )

    # ── Generation helpers ─────────────────────────────────────────────────

    async def pick_default_boq(self, project_id: uuid.UUID) -> uuid.UUID | None:
        """Find the largest BOQ for a project (used when caller omits boq_id).

        Returns the BOQ id with the most positions, or None if the project
        has no BOQs.
        """
        from app.modules.boq.repository import BOQRepository

        boq_repo = BOQRepository(self.session)
        boqs, _ = await boq_repo.list_for_project(project_id, limit=100)
        if not boqs:
            return None
        # Pick the most recently updated BOQ - that's the one the user is
        # actively working on. position_count is computed lazily so don't
        # rely on it here.
        sorted_boqs = sorted(boqs, key=lambda b: b.updated_at, reverse=True)
        return sorted_boqs[0].id

    async def _project_currency(self, project_id: uuid.UUID) -> str:
        """Return the project base currency, or '' when unavailable.

        Lazy-imports the projects module so costmodel does not hard-depend
        on it at import time (mirrors the BOQ repository imports above).
        """
        try:
            from app.modules.projects.repository import ProjectRepository

            project = await ProjectRepository(self.session).get_by_id(project_id)
        except Exception:
            logger.debug("Could not resolve project currency for %s", project_id)
            return ""
        return (project.currency or "") if project else ""

    async def apply_progress_earned_value(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
        percent_complete: Decimal,
    ) -> BudgetLine | None:
        """Persist EVM earned value on the budget line wired to a BOQ position.

        Called synchronously (same session / transaction) by the progress
        module after a progress entry is recorded. Semantics:

        * Progress percent is EARNED VALUE (BCWP), not actual cost - actuals
          keep flowing from invoices and are untouched here.
        * ``earned = position.total * percent_complete / 100`` - an absolute
          figure derived from the latest reading, so re-recording progress
          overwrites the previous earned value instead of accumulating.
        * If the position has no budget line yet (budget not generated), the
          update is skipped silently with a debug log.

        Args:
            project_id: Project the progress entry belongs to.
            boq_position_id: BOQ position the progress entry was recorded for.
            percent_complete: Latest cumulative percent complete in [0, 100].

        Returns:
            The updated budget line, or ``None`` when no budget line exists
            for the position (or the position itself is gone).
        """
        line = await self.budget_repo.get_by_position(project_id, boq_position_id)
        if line is None:
            logger.debug(
                "No budget line for position %s (project %s) - earned value skipped",
                boq_position_id,
                project_id,
            )
            return None

        from app.modules.boq.repository import PositionRepository

        position = await PositionRepository(self.session).get_by_id(boq_position_id)
        if position is None:
            logger.debug(
                "BOQ position %s not found - earned value skipped",
                boq_position_id,
            )
            return None

        total = _str_to_decimal(position.total)
        pct = max(Decimal("0"), min(Decimal("100"), percent_complete))
        earned = (total * pct / Decimal("100")).quantize(Decimal("0.01"))

        line_id = line.id
        await self.budget_repo.update_fields(line_id, earned_amount=earned)
        logger.info(
            "Earned value updated: position=%s line=%s pct=%s earned=%s",
            boq_position_id,
            line_id,
            pct,
            earned,
        )
        return await self.budget_repo.get_by_id(line_id)

    async def generate_budget_from_boq(self, project_id: uuid.UUID, boq_id: uuid.UUID) -> list[BudgetLine]:
        """Auto-generate budget lines from BOQ positions.

        Each BOQ position becomes a budget line with planned_amount = position total.
        Existing budget lines for the project are NOT deleted - new lines are appended.

        Idempotency (R5 audit, May 2026):
            Positions already wired to a budget line for this project are
            skipped. Re-running the endpoint after editing the BOQ creates
            lines only for the *new* positions. Pre-audit each call appended
            a fresh duplicate row per position, silently doubling BAC and
            poisoning every downstream EVM rollup.

        Args:
            project_id: Target project.
            boq_id: Source BOQ to generate budget from.

        Returns:
            List of newly created budget lines (empty if every position is
            already represented).
        """
        from app.modules.boq.repository import PositionRepository

        position_repo = PositionRepository(self.session)
        positions, _ = await position_repo.list_for_boq(boq_id, limit=10000)

        if not positions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No positions found in the specified BOQ",
            )

        # ── Idempotency guard ────────────────────────────────────────────
        # Skip positions that already have a budget line for this project.
        # This makes the endpoint safe to re-run after a BOQ edit; the
        # DB-level unique index added in the same migration is the belt to
        # this in-process suspenders.
        existing = await self.budget_repo.existing_position_ids(project_id)

        # Budget lines inherit the project base currency so EVM / cash-flow
        # rollups do not have to special-case the empty-string sentinel.
        # Exception (audit M4): planned/forecast amounts are the raw position
        # totals in the position's NATIVE currency, so a position imported
        # with a foreign currency marker keeps that currency stamp instead of
        # being mislabeled as base. The cash-flow generator converts per-line
        # currencies to base via the project FX map downstream.
        currency = await self._project_currency(project_id)
        project_ccy_norm = (currency or "").strip().upper()

        lines: list[BudgetLine] = []
        for pos in positions:
            if pos.id in existing:
                continue
            total = _str_to_decimal(pos.total)
            pos_meta = getattr(pos, "metadata_", None)
            pos_ccy = str(pos_meta.get("currency") or "").strip().upper() if isinstance(pos_meta, dict) else ""
            line_currency = pos_ccy if pos_ccy and pos_ccy != project_ccy_norm else currency
            line = BudgetLine(
                project_id=project_id,
                boq_position_id=pos.id,
                category="material",  # Default; user can reclassify later
                description=f"{pos.ordinal} - {pos.description[:200]}",
                planned_amount=str(total),
                committed_amount="0",
                actual_amount="0",
                forecast_amount=str(total),
                currency=line_currency,
            )
            lines.append(line)

        if not lines:
            logger.info(
                "generate_budget_from_boq: every BOQ position already wired (project=%s boq=%s); no-op.",
                project_id,
                boq_id,
            )
            return []

        created = await self.budget_repo.bulk_create(lines)

        await _safe_publish(
            "costmodel.budget.generated",
            {
                "project_id": str(project_id),
                "boq_id": str(boq_id),
                "lines_created": len(created),
            },
            source_module="oe_costmodel",
        )

        logger.info(
            "Generated %d budget lines from BOQ %s for project %s",
            len(created),
            boq_id,
            project_id,
        )
        return created

    async def generate_cash_flow_from_schedule(self, project_id: uuid.UUID) -> list[CashFlow]:
        """Generate cash flow entries by spreading budget line amounts across their schedule.

        For budget lines that have period_start and period_end, the planned_amount
        is evenly distributed across the months in that range.  Lines without a
        schedule are placed into a single 'unscheduled' entry.

        Currency handling (R5 audit, May 2026): every line is converted to
        the project base currency via ``fx_rates`` before being added to
        the period bucket. Pre-audit cash flow totals silently mixed USD,
        EUR, JPY values into one ``Decimal`` and the S-curve plotted the
        result as if they were all base - a 100 % bug for any multi-
        currency project.

        Args:
            project_id: Target project.

        Returns:
            List of newly created cash flow entries.
        """
        budget_lines, _ = await self.budget_repo.list_for_project(project_id, limit=10000)

        if not budget_lines:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No budget lines found for the project",
            )

        # FX context for currency conversion below.
        base_currency, fx_map = await self.budget_repo._project_fx_context(project_id)

        # Aggregate outflows per period (Decimal end-to-end, base currency)
        from app.modules.costmodel.repository import _amount_in_base

        period_outflows: dict[str, Decimal] = {}

        for bl in budget_lines:
            line_ccy = (bl.currency or "").strip().upper()
            amount = _amount_in_base(bl.planned_amount, line_ccy, base_currency, fx_map)
            if amount == 0:
                continue

            start = bl.period_start
            end = bl.period_end

            if start and end and len(start) >= 7 and len(end) >= 7:
                # Spread evenly across months
                months = _month_range(start[:7], end[:7])
                if months:
                    per_month = amount / len(months)
                    for m in months:
                        period_outflows[m] = period_outflows.get(m, Decimal("0")) + per_month
                else:
                    # Fallback: single period
                    p = start[:7]
                    period_outflows[p] = period_outflows.get(p, Decimal("0")) + amount
            else:
                # No schedule - use a generic unscheduled bucket.
                # Keep the sentinel <= 10 chars to fit the period column (varchar(10)).
                period_outflows["unsched"] = period_outflows.get("unsched", Decimal("0")) + amount

        # Build cash flow entries with running cumulative
        entries: list[CashFlow] = []
        cumulative = Decimal("0")

        for period in sorted(period_outflows.keys()):
            outflow = period_outflows[period]
            cumulative += outflow

            entry = CashFlow(
                project_id=project_id,
                period=period,
                category="total",
                planned_inflow="0",
                planned_outflow=str(round(float(outflow), 2)),
                actual_inflow="0",
                actual_outflow="0",
                cumulative_planned=str(round(float(cumulative), 2)),
                cumulative_actual="0",
            )
            entries.append(entry)

        created = await self.cashflow_repo.bulk_create(entries)

        await _safe_publish(
            "costmodel.cashflow.generated",
            {
                "project_id": str(project_id),
                "entries_created": len(created),
            },
            source_module="oe_costmodel",
        )

        logger.info(
            "Generated %d cash flow entries for project %s",
            len(created),
            project_id,
        )
        return created

    # ── Project Intelligence (RFC 25) ──────────────────────────────────────

    async def get_variance(self, project_id: uuid.UUID):
        """Compute the budget-variance KPI for the Estimation Dashboard.

        Budget is ``sum(unit_rate * quantity)`` across all positions of the
        largest BOQ for the project - there is no dedicated ``baseline_total``
        column in the Position model today, so the current rate is used as
        the baseline. ``current`` is the live ``sum(total)``; any manual
        overrides (totals that diverge from quantity * rate) therefore
        surface as variance.

        Empty projects return zeros and a neutral ``red_line`` of 5.0%.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.modules.boq.models import BOQ
        from app.modules.costmodel.schemas import VarianceResponse

        stmt = (
            select(BOQ)
            .options(selectinload(BOQ.positions))
            .where(BOQ.project_id == project_id)
            .order_by(BOQ.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        boqs = list(result.scalars().all())

        currency = await self._get_project_currency(project_id)

        if not boqs:
            return VarianceResponse(currency=currency)

        # Aggregate across every BOQ for the project - estimators usually
        # work in one BOQ, but summing protects us when multiple revisions
        # exist and all contribute to the live cost signal.
        budget = 0.0
        current = 0.0
        for boq in boqs:
            for pos in boq.positions:
                # Skip section headers (empty unit)
                if not pos.unit:
                    continue
                qty = _str_to_float(pos.quantity)
                rate = _str_to_float(pos.unit_rate)
                total = _str_to_float(pos.total)
                budget += qty * rate
                current += total

        variance_abs = round(current - budget, 2)
        variance_pct = round((current - budget) / budget * 100, 2) if budget > 0 else 0.0

        return VarianceResponse(
            budget=round(budget, 2),
            current=round(current, 2),
            variance_abs=variance_abs,
            variance_pct=variance_pct,
            red_line=5.0,
            currency=currency,
        )


def _month_range(start: str, end: str) -> list[str]:
    """Generate list of YYYY-MM strings from start to end (inclusive).

    Args:
        start: Start period in YYYY-MM format.
        end: End period in YYYY-MM format.

    Returns:
        List of YYYY-MM strings.
    """
    try:
        sy, sm = int(start[:4]), int(start[5:7])
        ey, em = int(end[:4]), int(end[5:7])
    except (ValueError, IndexError):
        return []

    months: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
        # Safety: cap at 120 months (10 years) to prevent runaway
        if len(months) > 120:
            break

    return months


# ── Cost Spine service (v6.4) ─────────────────────────────────────────────────


def _control_account_to_response(account: ControlAccount) -> ControlAccountResponse:
    """Convert a ControlAccount ORM row to its response schema."""
    return ControlAccountResponse.model_validate(account)


def _cost_line_to_response(line: CostLine) -> CostLineResponse:
    """Convert a CostLine ORM row to its response schema, money as Decimal."""
    return CostLineResponse(
        id=line.id,
        project_id=line.project_id,
        control_account_id=line.control_account_id,
        code=line.code,
        description=line.description,
        unit=line.unit,
        source=line.source,
        boq_position_id=line.boq_position_id,
        boq_id=line.boq_id,
        estimate_quantity=Decimal(str(line.estimate_quantity or "0")),
        estimate_unit_rate=Decimal(str(line.estimate_unit_rate or "0")),
        estimate_amount=Decimal(str(line.estimate_amount or "0")),
        currency=line.currency,
        status=line.status,
        metadata_=line.metadata_,
        created_at=line.created_at,
        updated_at=line.updated_at,
    )


def _account_code_from_classification(classification: object, standard: str) -> tuple[str, str] | None:
    """Derive ``(code, name)`` for a control account from a position classification.

    ``classification`` is the BOQ position JSONB, e.g.
    ``{"din276": "330", "masterformat": "04 20 00"}``. We pick the value for the
    requested ``standard`` (falling back to the first present standard) and use
    it as both the account code and a human label. Returns None when the
    position carries no usable classification so the caller can skip building an
    account for it.
    """
    if not isinstance(classification, dict) or not classification:
        return None
    # Prefer the configured standard, else the first non-empty entry.
    code = None
    if standard:
        raw = classification.get(standard)
        if raw not in (None, ""):
            code = str(raw).strip()
    if code is None:
        for value in classification.values():
            if value not in (None, ""):
                code = str(value).strip()
                break
    if not code:
        return None
    return code, code


class CostSpineService:
    """Business logic for the Cost Spine: control accounts, cost lines, rollups.

    Owns its own repositories and reuses the existing project-currency and
    event-publish helpers so FX and event semantics stay identical to the rest
    of the cost-model module.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.account_repo = ControlAccountRepository(session)
        self.line_repo = CostLineRepository(session)
        self.spine_repo = CostSpineRepository(session)
        self.budget_repo = BudgetLineRepository(session)
        # Reuse CostModelService helpers (project currency, default BOQ pick).
        self._cost_service = CostModelService(session)

    async def _get_project_currency(self, project_id: uuid.UUID) -> str:
        return await self._cost_service._get_project_currency(project_id)

    # ── Control accounts ────────────────────────────────────────────────────

    async def list_accounts(self, project_id: uuid.UUID) -> list[ControlAccountResponse]:
        """Return the project's control accounts as a tree-ordered list."""
        accounts = await self.account_repo.list_for_project(project_id)
        return [_control_account_to_response(a) for a in accounts]

    async def create_account(self, data: ControlAccountCreate) -> ControlAccountResponse:
        """Create a control account, rejecting a duplicate project+code (409)."""
        if data.project_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required")
        existing = await self.account_repo.get_by_project_code(data.project_id, data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Control account code '{data.code}' already exists in this project.",
            )
        if data.parent_id is not None:
            parent = await self.account_repo.get_by_id(data.parent_id)
            if parent is None or parent.project_id != data.project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="parent_id does not reference a control account in this project.",
                )
        account = ControlAccount(
            project_id=data.project_id,
            parent_id=data.parent_id,
            code=data.code,
            name=data.name,
            classification_standard=data.classification_standard,
            status=data.status,
            sort_order=data.sort_order,
            metadata_=data.metadata,
        )
        account = await self.account_repo.create(account)
        await _safe_publish(
            "costmodel.spine.account_created",
            {"account_id": str(account.id), "project_id": str(data.project_id), "code": data.code},
            source_module="oe_costmodel",
        )
        return _control_account_to_response(account)

    async def update_account(self, account_id: uuid.UUID, data: ControlAccountUpdate) -> ControlAccountResponse:
        """Update a control account. Raises 404 if missing, 409 on code clash."""
        account = await self.account_repo.get_by_id(account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control account not found")

        project_id = account.project_id
        fields = data.model_dump(exclude_unset=True)

        if "code" in fields and fields["code"] != account.code:
            clash = await self.account_repo.get_by_project_code(project_id, fields["code"])
            if clash is not None and clash.id != account_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Control account code '{fields['code']}' already exists in this project.",
                )
        if fields.get("parent_id") is not None:
            if fields["parent_id"] == account_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A control account cannot be its own parent.",
                )
            parent = await self.account_repo.get_by_id(fields["parent_id"])
            if parent is None or parent.project_id != project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="parent_id does not reference a control account in this project.",
                )
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.account_repo.update_fields(account_id, **fields)
        updated = await self.account_repo.get_by_id(account_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Control account not found after update",
            )
        return _control_account_to_response(updated)

    async def delete_account(self, account_id: uuid.UUID) -> None:
        """Delete a control account. Raises 404 if missing, 409 if lines reference it."""
        account = await self.account_repo.get_by_id(account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control account not found")
        referencing = await self.account_repo.count_lines_referencing(account_id)
        if referencing > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Control account is referenced by {referencing} cost line(s). "
                    "Reassign or delete those lines first."
                ),
            )
        project_id = str(account.project_id)
        await self.account_repo.delete(account_id)
        await _safe_publish(
            "costmodel.spine.account_deleted",
            {"account_id": str(account_id), "project_id": project_id},
            source_module="oe_costmodel",
        )

    # ── Cost lines ──────────────────────────────────────────────────────────

    async def list_lines(
        self,
        project_id: uuid.UUID,
        *,
        control_account_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[CostLineResponse]:
        """List cost lines for a project with optional account/status filters."""
        lines, _ = await self.line_repo.list_for_project(
            project_id,
            control_account_id=control_account_id,
            status=status,
            offset=offset,
            limit=limit,
        )
        return [_cost_line_to_response(line) for line in lines]

    async def create_line(self, data: CostLineCreate) -> CostLineResponse:
        """Create a cost line, auto-generating a code when omitted (409 on clash)."""
        if data.project_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required")

        code = (data.code or "").strip() or f"CL-{uuid.uuid4().hex[:8].upper()}"
        existing = await self.line_repo.get_by_project_code(data.project_id, code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cost line code '{code}' already exists in this project.",
            )
        if data.control_account_id is not None:
            account = await self.account_repo.get_by_id(data.control_account_id)
            if account is None or account.project_id != data.project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="control_account_id does not reference a control account in this project.",
                )
        currency = data.currency or await self._get_project_currency(data.project_id)
        line = CostLine(
            project_id=data.project_id,
            control_account_id=data.control_account_id,
            code=code,
            description=data.description,
            unit=data.unit,
            source=data.source,
            boq_position_id=data.boq_position_id,
            boq_id=data.boq_id,
            estimate_quantity=str(data.estimate_quantity),
            estimate_unit_rate=str(data.estimate_unit_rate),
            estimate_amount=str(data.estimate_amount),
            currency=currency,
            status=data.status,
            metadata_=data.metadata,
        )
        line = await self.line_repo.create(line)
        await _safe_publish(
            "costmodel.spine.cost_line_created",
            {"cost_line_id": str(line.id), "project_id": str(data.project_id), "code": code},
            source_module="oe_costmodel",
        )
        return _cost_line_to_response(line)

    async def update_line(self, line_id: uuid.UUID, data: CostLineUpdate) -> CostLineResponse:
        """Update a cost line. Raises 404 if missing, 409 on code clash."""
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")

        project_id = line.project_id
        fields = data.model_dump(exclude_unset=True)

        if "code" in fields and fields["code"] != line.code:
            clash = await self.line_repo.get_by_project_code(project_id, fields["code"])
            if clash is not None and clash.id != line_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cost line code '{fields['code']}' already exists in this project.",
                )
        if fields.get("control_account_id") is not None:
            account = await self.account_repo.get_by_id(fields["control_account_id"])
            if account is None or account.project_id != project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="control_account_id does not reference a control account in this project.",
                )
        for key in ("estimate_quantity", "estimate_unit_rate", "estimate_amount"):
            if key in fields and fields[key] is not None:
                fields[key] = str(fields[key])
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.line_repo.update_fields(line_id, **fields)
        updated = await self.line_repo.get_by_id(line_id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found after update")
        return _cost_line_to_response(updated)

    async def delete_line(self, line_id: uuid.UUID) -> None:
        """Delete a cost line. Raises 404 if missing, 409 if anything links to it."""
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")

        project_id = str(line.project_id)
        counts = await self._linked_counts(line_id, line.project_id)
        total_links = sum(counts.values())
        if total_links > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Cost line is still linked to downstream records. Unlink them first.",
                    "linked": counts,
                },
            )
        await self.line_repo.delete(line_id)
        await _safe_publish(
            "costmodel.spine.cost_line_deleted",
            {"cost_line_id": str(line_id), "project_id": project_id},
            source_module="oe_costmodel",
        )

    async def _linked_counts(self, line_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, int]:
        """Count downstream rows linked to a cost line (for delete-guard 409)."""
        from sqlalchemy import func, select

        from app.modules.boq.models import Position
        from app.modules.contracts.models import ContractLine
        from app.modules.procurement.models import MaterialRequisitionItem, PurchaseOrderItem

        async def _count(stmt: object) -> int:
            return (await self.session.execute(stmt)).scalar_one()

        budget = await _count(select(func.count()).where(BudgetLine.cost_line_id == line_id))
        positions = await _count(select(func.count()).where(Position.cost_line_id == line_id))
        po_items = await _count(select(func.count()).where(PurchaseOrderItem.cost_line_id == line_id))
        req_items = await _count(select(func.count()).where(MaterialRequisitionItem.cost_line_id == line_id))
        contract_lines = await _count(select(func.count()).where(ContractLine.cost_line_id == line_id))
        return {
            "budget_lines": budget,
            "boq_positions": positions,
            "po_items": po_items,
            "req_items": req_items,
            "contract_lines": contract_lines,
        }

    # ── Generation from BOQ ─────────────────────────────────────────────────

    async def generate_from_boq(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None = None,
    ) -> SpineGenerationResult:
        """Build the cost spine from a BOQ (idempotent on the BOQ position).

        Resolves the BOQ (largest/most-recent when ``boq_id`` is omitted), loads
        its positions, builds a control-account tree from each position's
        classification, and upserts exactly one cost line per BOQ position. The
        dedup key is the STABLE ``boq_position_id`` provenance, not the line
        ``code``: a position without a ``reference_code`` gets a random
        ``CL-XXXXXXXX`` code on first create, so keying on the code would never
        match across runs and would duplicate the whole batch every time. A new
        line copies the estimate quantity/rate/amount and inherits the project
        currency; an existing line is reused (its id and code kept) with the
        estimate refreshed from the current position. The position gets its
        ``cost_line_id`` written back and any budget line sharing the
        ``boq_position_id`` is auto-linked. Re-running creates zero new lines and
        accounts for both referenced and unreferenced positions.
        """
        from app.modules.boq.repository import BOQRepository, PositionRepository

        resolved_boq_id = boq_id
        if resolved_boq_id is None:
            resolved_boq_id = await self._cost_service.pick_default_boq(project_id)
            if resolved_boq_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No BOQ found for this project - create one first.",
                )

        # Confirm the BOQ belongs to this project (IDOR + correctness).
        boq = await BOQRepository(self.session).get_by_id(resolved_boq_id)
        if boq is None or boq.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ not found for this project",
            )

        position_repo = PositionRepository(self.session)
        positions, _ = await position_repo.list_for_boq(resolved_boq_id, limit=100000)
        if not positions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No positions found in the specified BOQ",
            )

        project_currency = await self._get_project_currency(project_id)

        # Resolve the classification standard once from the project config when
        # available; default to DIN 276 which is the most common in the seed set.
        standard = await self._resolve_classification_standard(project_id)

        # Cache existing accounts + lines so the whole generation is one pass.
        # Store only the account *id* (a plain UUID): the ORM object would be
        # expired by the first create/update inside the loop, and accessing
        # ``account.id`` afterwards would re-issue a sync SELECT and raise
        # MissingGreenlet under the async session.
        accounts_by_code: dict[str, uuid.UUID] = {
            a.code: a.id for a in await self.account_repo.list_for_project(project_id)
        }
        # Existing BOQ-sourced cost lines are deduped by their STABLE
        # ``boq_position_id`` - the true invariant is exactly one cost line per
        # BOQ position in a project. Keying on ``code`` was the original bug:
        # for a position with no ``reference_code`` the code is a random
        # ``CL-XXXX`` regenerated every run, so the previous line was never
        # matched and each re-run created a fresh duplicate batch (a real demo
        # BOQ went 129 -> 258 cost lines on the 2nd run).
        #
        # We snapshot only the identity + linkage columns into plain namespaces
        # up front. Reading the live ORM objects later in the loop would fault:
        # the first create/update flushes and ``expire_all()``s the identity
        # map, after which any ORM attribute access (even on a previously-loaded
        # row) re-issues a sync SELECT and raises MissingGreenlet under the
        # async session.
        lines_by_position: dict[str, SimpleNamespace] = {}
        for key, line in (await self.line_repo.existing_by_boq_position(project_id)).items():
            lines_by_position[key] = SimpleNamespace(
                id=line.id,
                code=line.code,
                boq_position_id=line.boq_position_id,
                boq_id=line.boq_id,
                control_account_id=line.control_account_id,
            )
        # All cost-line codes already taken in this project, so a freshly
        # generated ``CL-XXXX`` for an unreferenced position cannot collide with
        # an existing code (manual lines included). The unique
        # ``(project_id, code)`` constraint stays the DB-level belt to this.
        existing_codes: set[str] = {
            line.code for line in (await self.line_repo.list_for_project(project_id, limit=100000))[0]
        }

        accounts_created = 0
        cost_lines_created = 0
        positions_linked = 0

        # Snapshot every position attribute the loop needs BEFORE we mutate
        # anything. The first ``position_repo.update_fields`` / ``*_repo.create``
        # call inside the loop flushes and ``expire_all()``s the identity map;
        # without this snapshot the next iteration's ``pos.unit`` access would
        # trigger a sync lazy-load of an expired column and raise MissingGreenlet
        # under the async session. Reading the columns up front keeps generation
        # a single pass with no mid-loop expired-attribute IO.
        pos_views = [
            SimpleNamespace(
                id=pos.id,
                unit=pos.unit,
                classification=pos.classification,
                reference_code=getattr(pos, "reference_code", None),
                description=pos.description,
                quantity=pos.quantity,
                unit_rate=pos.unit_rate,
                total=pos.total,
                cost_line_id=getattr(pos, "cost_line_id", None),
            )
            for pos in positions
        ]

        for pos in pos_views:
            # Skip section headers (empty unit) - mirrors generate_budget_from_boq.
            if not pos.unit:
                continue

            # ── Control account from classification ──────────────────────
            account_id: uuid.UUID | None = None
            account_info = _account_code_from_classification(pos.classification, standard)
            if account_info is not None:
                acct_code, acct_name = account_info
                account_id = accounts_by_code.get(acct_code)
                if account_id is None:
                    account = ControlAccount(
                        project_id=project_id,
                        parent_id=None,
                        code=acct_code,
                        name=acct_name,
                        classification_standard=standard,
                        status="open",
                        sort_order=0,
                    )
                    account = await self.account_repo.create(account)
                    # Capture the id immediately; the ORM object expires on the
                    # next create/update inside this loop.
                    account_id = account.id
                    accounts_by_code[acct_code] = account_id
                    accounts_created += 1

            # ── Resolve the cost line by STABLE boq_position_id ──────────
            # Dedup on the position id, NOT the line code: an unreferenced
            # position has a random ``CL-XXXX`` code each run, so a 2nd
            # generate must find its line by the invariant provenance or it
            # would duplicate. A referenced position is matched the same way
            # once its line is wired (its ``boq_position_id`` is set on first
            # create), keeping the run idempotent regardless of reference_code.
            existing_line = lines_by_position.get(str(pos.id))
            if existing_line is None:
                # New line: code is the reference_code when present, else an
                # auto ``CL-XXXX`` that does not clash with an existing code.
                ref = (pos.reference_code or "").strip()
                code = ref or f"CL-{uuid.uuid4().hex[:8].upper()}"
                while not ref and code in existing_codes:
                    code = f"CL-{uuid.uuid4().hex[:8].upper()}"
                new_line = CostLine(
                    project_id=project_id,
                    control_account_id=account_id,
                    code=code,
                    description=(pos.description or "")[:2000],
                    unit=pos.unit,
                    source="boq",
                    boq_position_id=pos.id,
                    boq_id=resolved_boq_id,
                    estimate_quantity=str(pos.quantity or "0"),
                    estimate_unit_rate=str(pos.unit_rate or "0"),
                    estimate_amount=str(pos.total or "0"),
                    currency=project_currency,
                    status="active",
                )
                new_line = await self.line_repo.create(new_line)
                # Capture identity NOW, before the next iteration expires it.
                view = SimpleNamespace(
                    id=new_line.id,
                    code=code,
                    boq_position_id=pos.id,
                    boq_id=resolved_boq_id,
                    control_account_id=account_id,
                )
                lines_by_position[str(pos.id)] = view
                existing_codes.add(code)
                cost_lines_created += 1
            else:
                # Reuse the existing line: keep its id + code, refresh the
                # estimate from the current BOQ position, and fill any missing
                # linkage. This keeps exactly one cost line per position and
                # tracks edits to the BOQ without duplicating rows.
                view = existing_line
                fill: dict[str, object] = {
                    "estimate_quantity": str(pos.quantity or "0"),
                    "estimate_unit_rate": str(pos.unit_rate or "0"),
                    "estimate_amount": str(pos.total or "0"),
                }
                if view.boq_id is None:
                    fill["boq_id"] = resolved_boq_id
                    view.boq_id = resolved_boq_id
                if view.control_account_id is None and account_id is not None:
                    fill["control_account_id"] = account_id
                    view.control_account_id = account_id
                await self.line_repo.update_fields(view.id, **fill)

            # ── Write cost_line_id back onto the position (fill-only) ────
            if pos.cost_line_id is None:
                await position_repo.update_fields(pos.id, cost_line_id=view.id)
                positions_linked += 1

        # ── Auto-link budget lines by boq_position_id (fill-nulls-only) ──
        # ``lines_by_position`` values are plain namespaces (id + linkage cols),
        # so the autolink pass never touches expired ORM state.
        budget_lines_linked = await self._autolink_budget_lines(project_id, lines_by_position)

        await _safe_publish(
            "costmodel.spine.generated",
            {
                "project_id": str(project_id),
                "boq_id": str(resolved_boq_id),
                "accounts_created": accounts_created,
                "cost_lines_created": cost_lines_created,
                "positions_linked": positions_linked,
                "budget_lines_linked": budget_lines_linked,
            },
            source_module="oe_costmodel",
        )
        logger.info(
            "Cost spine generated: project=%s boq=%s accounts=+%d lines=+%d positions_linked=%d budget_linked=%d",
            project_id,
            resolved_boq_id,
            accounts_created,
            cost_lines_created,
            positions_linked,
            budget_lines_linked,
        )
        return SpineGenerationResult(
            project_id=project_id,
            boq_id=resolved_boq_id,
            accounts_created=accounts_created,
            cost_lines_created=cost_lines_created,
            positions_linked=positions_linked,
            budget_lines_linked=budget_lines_linked,
        )

    async def _resolve_classification_standard(self, project_id: uuid.UUID) -> str:
        """Best-effort project classification standard, defaulting to ``din276``."""
        try:
            from app.modules.projects.repository import ProjectRepository

            project = await ProjectRepository(self.session).get_by_id(project_id)
        except Exception:
            return "din276"
        if project is None:
            return "din276"
        cfg = getattr(project, "config", None) or getattr(project, "settings", None)
        if isinstance(cfg, dict):
            std = str(cfg.get("classification_standard") or "").strip()
            if std:
                return std
        return "din276"

    async def _autolink_budget_lines(
        self,
        project_id: uuid.UUID,
        lines_by_position: dict[str, SimpleNamespace],
    ) -> int:
        """Link existing budget lines to cost lines by shared ``boq_position_id``.

        Fill-nulls-only: a budget line already carrying a ``cost_line_id`` is
        left untouched. Sets both ``cost_line_id`` and ``control_account_id`` so
        account rollups can group budget without re-joining.

        ``lines_by_position`` is keyed by ``str(boq_position_id)`` and its
        values are plain namespaces (id + linkage cols) captured by the
        generation loop, so this pass never reads an expired ORM attribute.
        Budget-line fields are likewise snapshotted before the first
        ``update_fields`` (which ``expire_all()``s) so a multi-row link does not
        fault on the second iteration.
        """
        # Cost lines are already keyed by their originating position; keep only
        # those that actually carry a position id.
        by_position: dict[str, SimpleNamespace] = {
            key: line for key, line in lines_by_position.items() if line.boq_position_id is not None
        }

        if not by_position:
            return 0

        budget_lines, _ = await self.budget_repo.list_for_project(project_id, limit=100000)
        # Snapshot the columns we branch on up front (see docstring).
        bl_views = [
            SimpleNamespace(
                id=bl.id,
                cost_line_id=bl.cost_line_id,
                boq_position_id=bl.boq_position_id,
            )
            for bl in budget_lines
        ]
        linked = 0
        for bl in bl_views:
            if bl.cost_line_id is not None or bl.boq_position_id is None:
                continue
            target = by_position.get(str(bl.boq_position_id))
            if target is None:
                continue
            await self.budget_repo.update_fields(
                bl.id,
                cost_line_id=target.id,
                control_account_id=target.control_account_id,
            )
            linked += 1
        return linked

    # ── Rollup ──────────────────────────────────────────────────────────────

    async def _build_links(self, project_id: uuid.UUID) -> dict[str, CostLineLinks]:
        """Collect every downstream reference per cost line in one sweep each.

        Returns a dict keyed by cost-line id string. Five scans (budget, BOQ
        positions, PO items, contract lines, RFQs) - no per-line queries.
        """
        from sqlalchemy import select

        from app.modules.boq.models import Position
        from app.modules.contracts.models import Contract, ContractLine
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
        from app.modules.rfq_bidding.models import RFQ

        links: dict[str, CostLineLinks] = {}

        def _bucket(key: str) -> CostLineLinks:
            return links.setdefault(key, CostLineLinks())

        # Budget lines.
        stmt = select(BudgetLine.cost_line_id, BudgetLine.id).where(
            BudgetLine.project_id == project_id,
            BudgetLine.cost_line_id.is_not(None),
        )
        for cost_line_id, bl_id in (await self.session.execute(stmt)).all():
            _bucket(str(cost_line_id)).budget_line_ids.append(str(bl_id))

        # BOQ positions.
        stmt = select(Position.cost_line_id, Position.id).where(Position.cost_line_id.is_not(None))
        for cost_line_id, pos_id in (await self.session.execute(stmt)).all():
            _bucket(str(cost_line_id)).boq_position_ids.append(str(pos_id))

        # PO items (scoped to project via the parent PO).
        stmt = (
            select(PurchaseOrderItem.cost_line_id, PurchaseOrderItem.id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.po_id)
            .where(
                PurchaseOrder.project_id == project_id,
                PurchaseOrderItem.cost_line_id.is_not(None),
            )
        )
        for cost_line_id, item_id in (await self.session.execute(stmt)).all():
            _bucket(str(cost_line_id)).po_item_ids.append(str(item_id))

        # Contract lines (scoped to project via the parent contract).
        stmt = (
            select(ContractLine.cost_line_id, ContractLine.id)
            .join(Contract, Contract.id == ContractLine.contract_id)
            .where(
                Contract.project_id == project_id,
                ContractLine.cost_line_id.is_not(None),
            )
        )
        for cost_line_id, cl_id in (await self.session.execute(stmt)).all():
            _bucket(str(cost_line_id)).contract_line_ids.append(str(cl_id))

        # RFQs carry a JSON array of cost-line ids.
        stmt = select(RFQ.id, RFQ.cost_line_ids).where(RFQ.project_id == project_id)
        for rfq_id, cost_line_ids in (await self.session.execute(stmt)).all():
            if isinstance(cost_line_ids, list):
                for raw in cost_line_ids:
                    if raw:
                        _bucket(str(raw)).rfq_ids.append(str(rfq_id))

        return links

    def _assemble_line_rollup(
        self,
        line: CostLine,
        *,
        budget: dict[str, dict[str, Decimal]],
        po: dict[str, Decimal],
        contracted: dict[str, Decimal],
        claimed: dict[str, Decimal],
        links: dict[str, CostLineLinks],
    ) -> CostLineRollupResponse:
        """Assemble one cost line's rollup from the pre-computed aggregate maps."""
        key = str(line.id)
        b = budget.get(key, {})
        budget_planned = b.get("planned", Decimal("0"))
        estimate_amount = Decimal(str(line.estimate_amount or "0"))
        return CostLineRollupResponse(
            cost_line_id=line.id,
            code=line.code,
            control_account_id=line.control_account_id,
            description=line.description,
            currency=line.currency,
            estimate_amount=estimate_amount,
            budget_planned=budget_planned,
            budget_committed=b.get("committed", Decimal("0")),
            budget_actual=b.get("actual", Decimal("0")),
            po_committed=po.get(key, Decimal("0")),
            contracted_value=contracted.get(key, Decimal("0")),
            claimed_to_date=claimed.get(key, Decimal("0")),
            variance_estimate_vs_budget=estimate_amount - budget_planned,
            links=links.get(key, CostLineLinks()),
        )

    async def _distinct_link_currencies(self, project_id: uuid.UUID) -> set[str]:
        """Distinct non-blank currencies across the linked cost-domain rows.

        Mirrors the existing ``_distinct_budget_currencies`` flag pattern but
        spans every spine source (budget lines, PO currency, contract currency,
        cost-line currency) so ``mixed_currency`` is True whenever a sum may
        have crossed a missing fx rate.
        """
        from sqlalchemy import select

        from app.modules.contracts.models import Contract, ContractLine
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

        codes: set[str] = set()

        stmt = select(CostLine.currency).where(CostLine.project_id == project_id).distinct()
        for (raw,) in (await self.session.execute(stmt)).all():
            if (raw or "").strip():
                codes.add(raw.strip().upper())

        stmt = (
            select(BudgetLine.currency)
            .where(BudgetLine.project_id == project_id, BudgetLine.cost_line_id.is_not(None))
            .distinct()
        )
        for (raw,) in (await self.session.execute(stmt)).all():
            if (raw or "").strip():
                codes.add(raw.strip().upper())

        stmt = (
            select(PurchaseOrder.currency_code)
            .join(PurchaseOrderItem, PurchaseOrderItem.po_id == PurchaseOrder.id)
            .where(PurchaseOrder.project_id == project_id, PurchaseOrderItem.cost_line_id.is_not(None))
            .distinct()
        )
        for (raw,) in (await self.session.execute(stmt)).all():
            if (raw or "").strip():
                codes.add(raw.strip().upper())

        stmt = (
            select(Contract.currency)
            .join(ContractLine, ContractLine.contract_id == Contract.id)
            .where(Contract.project_id == project_id, ContractLine.cost_line_id.is_not(None))
            .distinct()
        )
        for (raw,) in (await self.session.execute(stmt)).all():
            if (raw or "").strip():
                codes.add(raw.strip().upper())

        return codes

    async def rollup_for_project(self, project_id: uuid.UUID) -> SpineRollupResponse:
        """Assemble the project-wide Cost Spine rollup from grouped aggregates."""
        accounts = await self.account_repo.list_for_project(project_id)
        lines, _ = await self.line_repo.list_for_project(project_id, limit=100000)

        budget = await self.spine_repo.budget_aggregate_by_cost_line(project_id)
        po = await self.spine_repo.po_committed_by_cost_line(project_id)
        contracted = await self.spine_repo.contract_value_by_cost_line(project_id)
        claimed = await self.spine_repo.claimed_to_date_by_cost_line(project_id)
        links = await self._build_links(project_id)

        line_rollups = [
            self._assemble_line_rollup(
                line,
                budget=budget,
                po=po,
                contracted=contracted,
                claimed=claimed,
                links=links,
            )
            for line in lines
        ]

        totals = {
            "estimate_amount": Decimal("0"),
            "budget_planned": Decimal("0"),
            "budget_committed": Decimal("0"),
            "budget_actual": Decimal("0"),
            "po_committed": Decimal("0"),
            "contracted_value": Decimal("0"),
            "claimed_to_date": Decimal("0"),
        }
        for r in line_rollups:
            totals["estimate_amount"] += r.estimate_amount
            totals["budget_planned"] += r.budget_planned
            totals["budget_committed"] += r.budget_committed
            totals["budget_actual"] += r.budget_actual
            totals["po_committed"] += r.po_committed
            totals["contracted_value"] += r.contracted_value
            totals["claimed_to_date"] += r.claimed_to_date
        totals_str = {k: str(v) for k, v in totals.items()}
        totals_str["variance_estimate_vs_budget"] = str(totals["estimate_amount"] - totals["budget_planned"])

        currency = await self._get_project_currency(project_id)
        mixed = len(await self._distinct_link_currencies(project_id)) > 1

        return SpineRollupResponse(
            currency=currency,
            mixed_currency=mixed,
            accounts=[_control_account_to_response(a) for a in accounts],
            lines=line_rollups,
            totals=totals_str,
        )

    async def rollup_for_line(self, line_id: uuid.UUID) -> CostLineRollupResponse:
        """Assemble the rollup for a single cost line. Raises 404 if missing."""
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")

        project_id = line.project_id
        budget = await self.spine_repo.budget_aggregate_by_cost_line(project_id)
        po = await self.spine_repo.po_committed_by_cost_line(project_id)
        contracted = await self.spine_repo.contract_value_by_cost_line(project_id)
        claimed = await self.spine_repo.claimed_to_date_by_cost_line(project_id)
        links = await self._build_links(project_id)

        return self._assemble_line_rollup(
            line,
            budget=budget,
            po=po,
            contracted=contracted,
            claimed=claimed,
            links=links,
        )

    # ── Link / unlink a downstream target ─────────────────────────────────────

    async def link_target(
        self,
        line_id: uuid.UUID,
        target_type: str,
        target_id: uuid.UUID,
    ) -> CostLineRollupResponse:
        """Link a downstream entity to a cost line, then return its rollup.

        ``target_type`` is one of ``boq_position`` / ``budget_line`` /
        ``po_item`` / ``contract_line`` / ``rfq``. The target must belong to the
        same project as the cost line (404 on a cross-project / missing target).
        """
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
        await self._apply_link(line, target_type, target_id, link=True)
        return await self.rollup_for_line(line_id)

    async def unlink_target(
        self,
        line_id: uuid.UUID,
        target_type: str,
        target_id: uuid.UUID,
    ) -> CostLineRollupResponse:
        """Detach a downstream entity from a cost line, then return its rollup."""
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
        await self._apply_link(line, target_type, target_id, link=False)
        return await self.rollup_for_line(line_id)

    async def _apply_link(
        self,
        line: CostLine,
        target_type: str,
        target_id: uuid.UUID,
        *,
        link: bool,
    ) -> None:
        """Set or clear ``cost_line_id`` on the target row after a project check."""
        from sqlalchemy import update

        from app.modules.boq.models import BOQ, Position
        from app.modules.contracts.models import Contract, ContractLine
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
        from app.modules.rfq_bidding.models import RFQ

        project_id = line.project_id
        new_value = line.id if link else None
        normalized = (target_type or "").strip().lower()

        if normalized == "boq_position":
            pos = await self.session.get(Position, target_id)
            if pos is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            boq = await self.session.get(BOQ, pos.boq_id)
            if boq is None or boq.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            await self.session.execute(update(Position).where(Position.id == target_id).values(cost_line_id=new_value))

        elif normalized == "budget_line":
            bl = await self.session.get(BudgetLine, target_id)
            if bl is None or bl.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            await self.budget_repo.update_fields(
                target_id,
                cost_line_id=new_value,
                control_account_id=(line.control_account_id if link else None),
            )

        elif normalized == "po_item":
            item = await self.session.get(PurchaseOrderItem, target_id)
            if item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            po = await self.session.get(PurchaseOrder, item.po_id)
            if po is None or po.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            await self.session.execute(
                update(PurchaseOrderItem).where(PurchaseOrderItem.id == target_id).values(cost_line_id=new_value)
            )

        elif normalized == "contract_line":
            cl = await self.session.get(ContractLine, target_id)
            if cl is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            contract = await self.session.get(Contract, cl.contract_id)
            if contract is None or contract.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            await self.session.execute(
                update(ContractLine).where(ContractLine.id == target_id).values(cost_line_id=new_value)
            )

        elif normalized == "rfq":
            rfq = await self.session.get(RFQ, target_id)
            if rfq is None or rfq.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
            current = list(rfq.cost_line_ids or [])
            line_id_str = str(line.id)
            if link:
                if line_id_str not in {str(c) for c in current}:
                    current.append(line_id_str)
            else:
                current = [c for c in current if str(c) != line_id_str]
            await self.session.execute(update(RFQ).where(RFQ.id == target_id).values(cost_line_ids=current))
            await self.session.flush()
            self.session.expire_all()

        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Invalid target_type. Expected one of: boq_position, budget_line, po_item, contract_line, rfq."
                ),
            )

        await self.session.flush()
        self.session.expire_all()

    # ── Actual-cost posting (Gap B - shared spine method) ─────────────────────

    async def post_actual_to_budget_line(
        self,
        project_id: uuid.UUID,
        cost_line_id: uuid.UUID | None,
        cost_category: str | None,
        amount_base: str,
        currency: str,
        source_kind: str,
        source_ref: str,
        *,
        idempotency_key: str,
    ) -> BudgetLine:
        """Idempotently upsert ``BudgetLine.actual_amount`` from an actual cost.

        This is the single shared sink for posting realised cost into the cost
        spine. Finance calls it when an invoice is paid; Gaps A/C/E (labour,
        equipment, certified-claim receivable) will call it later for their own
        ``source_kind``. Keeping the posting logic here means every actual lands
        with identical idempotency, FX-audit and event semantics.

        Semantics:
            * Resolves (or creates) the budget row matching
              ``(project_id, cost_line_id, cost_category)``. ``cost_category``
              ``None`` is stored as ``""`` (the NOT-NULL column sentinel for
              "uncategorised") so a headerless posting lands on one stable row.
            * Increments ``actual_amount`` by ``amount_base`` (Decimal end to
              end; ``amount_base`` is already in the project base currency -
              the caller is responsible for FX conversion and must NEVER zero a
              foreign value when a rate is missing).
            * Idempotent on ``(source_kind, source_ref)``: the posting is
              recorded in ``metadata.postings``; re-posting the same source is a
              no-op that returns the row unchanged. ``idempotency_key`` is
              stored alongside for the caller's own audit/replay correlation.
            * Emits ``costmodel.budget_line.actual_posted`` on a real change.

        Args:
            project_id: Owning project (must exist and carry a base currency).
            cost_line_id: Optional cost-spine link; when set must belong to the
                project.
            cost_category: One of the allowed categories, or ``None`` /
                ``""`` for uncategorised.
            amount_base: Decimal-as-string amount in the project base currency.
            currency: Original source-line currency, recorded for audit only.
            source_kind: Posting source family (e.g. ``"invoice_paid"``).
            source_ref: Stable unique reference within the source family
                (e.g. ``"{invoice_id}:{item_id}"``).
            idempotency_key: Caller-supplied replay token (recorded in the
                posting trail).

        Returns:
            The created or updated ``BudgetLine`` row (or the unchanged row when
            the posting was already applied).

        Raises:
            HTTPException: 404 when the project / cost line is missing or
                cross-project; 400 when the project has no base currency, the
                category is unknown, or the amount is not a finite number.
        """
        # ── 1. Validate project + base currency ──────────────────────────
        base_currency = await self._get_project_currency(project_id)
        if not base_currency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Project has no base currency configured - cannot post an "
                    "actual cost without a currency to denominate it in."
                ),
            )

        # ── 2. Validate cost line belongs to the project (when supplied) ──
        control_account_id: uuid.UUID | None = None
        if cost_line_id is not None:
            cost_line = await self.line_repo.get_by_id(cost_line_id)
            if cost_line is None or cost_line.project_id != project_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="cost_line_id does not reference a cost line in this project.",
                )
            control_account_id = cost_line.control_account_id

        # ── 3. Validate category ──────────────────────────────────────────
        normalized_category = (cost_category or "").strip().lower()
        if normalized_category and normalized_category not in _ACTUAL_COST_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unknown cost_category '{cost_category}'. Allowed: {', '.join(sorted(_ACTUAL_COST_CATEGORIES))}."
                ),
            )

        # ── 4. Validate amount ────────────────────────────────────────────
        try:
            amount = Decimal(str(amount_base))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid amount_base: {amount_base!r}",
            ) from exc
        if not amount.is_finite():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Non-finite amount_base: {amount_base!r}",
            )

        # ── 5. Resolve or create the target budget line ───────────────────
        line = await self.budget_repo.find_for_actual_posting(
            project_id,
            cost_line_id=cost_line_id,
            category=normalized_category,
        )

        # Quantize to 2dp once so the posting trail amount matches exactly what
        # is added to actual_amount (no "900.0" vs "900.00" audit mismatch).
        amount = amount.quantize(Decimal("0.01"))
        posting_entry = {
            "source_kind": source_kind,
            "source_ref": source_ref,
            "idempotency_key": idempotency_key,
            "amount": str(amount),
            "currency": currency or "",
            "posted_at": datetime.now(UTC).isoformat(),
        }

        if line is None:
            # New row: actual_amount = amount, seed the posting trail.
            line = BudgetLine(
                project_id=project_id,
                cost_line_id=cost_line_id,
                control_account_id=control_account_id,
                category=normalized_category,
                description="Actual cost (auto)",
                planned_amount="0",
                committed_amount="0",
                actual_amount=str(amount),
                forecast_amount="0",
                currency=base_currency,
                metadata_={"kind": _ACTUAL_POSTING_MARKER, "postings": [posting_entry]},
            )
            line = await self.budget_repo.create(line)
            # Capture identity/linkage NOW - a later session.expire_all (none
            # here, but kept for symmetry) must never force a sync lazy-load.
            await self._publish_actual_posted(
                budget_line_id=line.id,
                project_id=project_id,
                cost_line_id=cost_line_id,
                category=normalized_category,
                source_kind=source_kind,
                source_ref=source_ref,
                amount=amount,
            )
            logger.info(
                "Actual posted (new line): project=%s line=%s kind=%s ref=%s +%s",
                project_id,
                line.id,
                source_kind,
                source_ref,
                amount,
            )
            return line

        # ── 6. Existing row: idempotency check on (source_kind, source_ref)
        # Snapshot every attribute we need BEFORE update_fields() calls
        # expire_all(): reading line.* afterwards would re-issue a sync SELECT
        # and raise MissingGreenlet under the async session.
        line_id = line.id
        existing_cost_line_id = line.cost_line_id
        line_category = line.category or ""
        md = dict(line.metadata_) if isinstance(line.metadata_, dict) else {}
        postings = md.get("postings")
        if not isinstance(postings, list):
            postings = []
        already = any(
            isinstance(p, dict) and p.get("source_kind") == source_kind and p.get("source_ref") == source_ref
            for p in postings
        )
        if already:
            # Replay - return the row unchanged (no event, no double count).
            logger.info(
                "Actual posting skipped (already applied): project=%s line=%s kind=%s ref=%s",
                project_id,
                line_id,
                source_kind,
                source_ref,
            )
            refreshed = await self.budget_repo.get_by_id(line_id)
            return refreshed if refreshed is not None else line

        prior = _str_to_decimal(line.actual_amount)
        new_actual = (prior + amount).quantize(Decimal("0.01"))
        postings = [*postings, posting_entry]
        md["postings"] = postings
        if md.get("kind") is None:
            md["kind"] = _ACTUAL_POSTING_MARKER

        # Fill a missing cost-line / account link if this posting carries one
        # (a budget line created before the spine may now learn its link).
        fill: dict[str, object] = {"actual_amount": str(new_actual), "metadata_": md}
        resolved_cost_line_id = existing_cost_line_id
        if existing_cost_line_id is None and cost_line_id is not None:
            fill["cost_line_id"] = cost_line_id
            resolved_cost_line_id = cost_line_id
            if control_account_id is not None:
                fill["control_account_id"] = control_account_id

        await self.budget_repo.update_fields(line_id, **fill)
        await self._publish_actual_posted(
            budget_line_id=line_id,
            project_id=project_id,
            cost_line_id=resolved_cost_line_id,
            category=line_category,
            source_kind=source_kind,
            source_ref=source_ref,
            amount=amount,
        )
        logger.info(
            "Actual posted (increment): project=%s line=%s kind=%s ref=%s +%s -> %s",
            project_id,
            line_id,
            source_kind,
            source_ref,
            amount,
            new_actual,
        )

        updated = await self.budget_repo.get_by_id(line_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Budget line not found after posting",
            )
        return updated

    @staticmethod
    async def _publish_actual_posted(
        *,
        budget_line_id: uuid.UUID,
        project_id: uuid.UUID,
        cost_line_id: uuid.UUID | None,
        category: str,
        source_kind: str,
        source_ref: str,
        amount: Decimal,
    ) -> None:
        """Emit ``costmodel.budget_line.actual_posted`` for downstream consumers.

        Takes only primitives (never an ORM row) so the publish never reads an
        attribute the surrounding ``update_fields`` / ``expire_all`` may have
        expired - that would re-issue a sync SELECT and raise MissingGreenlet
        under the async session. Gap D (cost-overrun alerts) and reporting
        subscribe here.
        """
        from app.modules.costmodel.events import EVENT_BUDGET_LINE_ACTUAL_POSTED

        await _safe_publish(
            EVENT_BUDGET_LINE_ACTUAL_POSTED,
            {
                "project_id": str(project_id),
                "budget_line_id": str(budget_line_id),
                "cost_line_id": str(cost_line_id) if cost_line_id else None,
                "category": category or "",
                "source_kind": source_kind,
                "source_ref": source_ref,
                "amount": str(amount),
            },
            source_module="oe_costmodel",
        )


# ── Labour actuals (field labour -> budget) ────────────────────────────────────


# Marker used to find/track the single auto-maintained labour budget line per
# project, and to record which (report_id, status) pairs have already been
# folded into ``actual_amount`` so a submit -> approve pair never double-counts.
_LABOUR_LINE_MARKER = "labour_actuals_auto"


class LabourActualsService:
    """Roll field-reported labour hours into the project budget actuals.

    Subscribes (via :data:`event_bus`) to ``fieldreports.labour.logged`` and,
    for each event, converts every workforce row's ``hours x cost_rate`` into
    the project base currency and accumulates the total onto a single
    auto-maintained ``category="labor"`` budget line. The line is found /
    created idempotently per project (tagged via ``metadata.kind``), and each
    event is applied at most once (the ``(report_id, status)`` key is recorded
    in the line metadata).

    FX is never blended: a row's own currency (explicit, or the resource's
    currency) is converted to the project base via the project ``fx_rates``
    using the shared :func:`_amount_in_base` helper.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.budget_repo = BudgetLineRepository(session)

    @staticmethod
    def _to_decimal(value: object) -> Decimal:
        if value is None:
            return Decimal("0")
        try:
            d = Decimal(str(value))
        except (ValueError, ArithmeticError, TypeError):
            return Decimal("0")
        return d if d.is_finite() and d >= 0 else Decimal("0")

    async def _resource_rate(self, resource_id: str) -> tuple[Decimal, str]:
        """Return ``(default_cost_rate, currency)`` for a resource, or (0, "")."""
        try:
            rid = uuid.UUID(str(resource_id))
        except (ValueError, AttributeError, TypeError):
            return Decimal("0"), ""
        try:
            from app.modules.resources.repository import ResourceRepository

            resource = await ResourceRepository(self.session).get_by_id(rid)
        except Exception:
            return Decimal("0"), ""
        if resource is None:
            return Decimal("0"), ""
        rate = resource.default_cost_rate if resource.default_cost_rate is not None else Decimal("0")
        return self._to_decimal(rate), (resource.currency or "").strip().upper()

    async def compute_labour_cost(
        self,
        project_id: uuid.UUID,
        rows: list[dict],
    ) -> Decimal:
        """Compute the total labour cost of ``rows`` in the project base currency.

        Pure aggregation (no writes) so it is unit-testable in isolation:
        for each row, ``hours x rate`` is evaluated in the row's own currency,
        then converted to base via ``_amount_in_base``. A row with neither an
        explicit ``cost_rate`` nor a resolvable resource rate contributes 0.
        """
        base, fx = await self.budget_repo._project_fx_context(project_id)
        total = Decimal("0")
        for row in rows:
            if not isinstance(row, dict):
                continue
            hours = self._to_decimal(row.get("hours"))
            if hours <= 0:
                continue

            rate = self._to_decimal(row.get("cost_rate"))
            row_ccy = (str(row.get("currency") or "")).strip().upper()
            if rate <= 0 and row.get("resource_id"):
                rate, res_ccy = await self._resource_rate(str(row["resource_id"]))
                if not row_ccy:
                    row_ccy = res_ccy
            if rate <= 0:
                continue

            amount_native = hours * rate
            total += _amount_in_base(str(amount_native), row_ccy, base, fx)
        return total

    async def _get_or_create_labour_line(self, project_id: uuid.UUID) -> BudgetLine:
        """Find (or create) the single auto-maintained labour budget line."""
        lines, _ = await self.budget_repo.list_for_project(project_id, category="labor", limit=1000)
        for line in lines:
            md = line.metadata_ if isinstance(line.metadata_, dict) else {}
            if md.get("kind") == _LABOUR_LINE_MARKER:
                return line

        currency = await CostModelService(self.session)._get_project_currency(project_id)
        line = BudgetLine(
            project_id=project_id,
            category="labor",
            description="Field labour (auto)",
            planned_amount="0",
            committed_amount="0",
            actual_amount="0",
            forecast_amount="0",
            currency=currency,
            metadata_={"kind": _LABOUR_LINE_MARKER, "applied_events": []},
        )
        return await self.budget_repo.create(line)

    async def apply_labour_event(
        self,
        *,
        project_id: uuid.UUID,
        report_id: str,
        status_value: str,
        rows: list[dict],
    ) -> Decimal:
        """Fold one labour event into the labour budget line's ``actual_amount``.

        Idempotent on ``(report_id, status_value)``: re-firing the same event
        (or a submit followed by an approve carrying identical hours) adds the
        amount at most once. Returns the amount applied (0 when skipped).
        """
        amount = await self.compute_labour_cost(project_id, rows)
        if amount <= 0:
            return Decimal("0")

        line = await self._get_or_create_labour_line(project_id)
        md = dict(line.metadata_) if isinstance(line.metadata_, dict) else {}
        applied = md.get("applied_events")
        if not isinstance(applied, list):
            applied = []
        event_key = f"{report_id}:{status_value}"
        if event_key in applied:
            return Decimal("0")  # already counted

        prior = self._to_decimal(line.actual_amount)
        new_actual = (prior + amount).quantize(Decimal("0.01"))
        applied = [*applied, event_key]
        md["applied_events"] = applied

        await self.budget_repo.update_fields(
            line.id,
            actual_amount=str(new_actual),
            metadata_=md,
        )
        logger.info(
            "Labour actuals: project=%s report=%s status=%s +%s -> %s",
            project_id,
            report_id,
            status_value,
            amount,
            new_actual,
        )
        return amount


async def _on_labour_logged(event: object) -> None:
    """Detached subscriber: roll a labour event into budget actuals.

    Opens its own session (the publisher is still inside its request
    transaction) and swallows errors so a cost-rollup failure never breaks
    the field-report / diary submission that triggered it.
    """
    data = getattr(event, "data", None) or {}
    rows = data.get("rows")
    project_id_raw = data.get("project_id")
    report_id = str(data.get("report_id") or "")
    status_value = str(data.get("status") or "")
    if not project_id_raw or not isinstance(rows, list) or not rows:
        return
    try:
        project_id = uuid.UUID(str(project_id_raw))
    except (ValueError, AttributeError, TypeError):
        return

    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            service = LabourActualsService(session)
            await service.apply_labour_event(
                project_id=project_id,
                report_id=report_id,
                status_value=status_value,
                rows=rows,
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Labour actuals rollup failed for report=%s - source submission unaffected",
            report_id,
        )


# Register the subscriber at import time. The module loader imports
# ``costmodel.events`` (absent) AND ``costmodel.service`` indirectly via the
# router, so binding here keeps the wiring inside an allowed file. Guard
# against double-registration on repeated imports (test reload, etc.).
if _on_labour_logged not in event_bus._handlers.get("fieldreports.labour.logged", []):
    event_bus.subscribe("fieldreports.labour.logged", _on_labour_logged)


# ── Cost-overrun alerts (Gap D - actual breaches planned + threshold) ─────────


class CostOverrunAlertService:
    """Decide whether a budget line's actual cost has breached its alert
    threshold, and (when it has) notify the project owner at most once per
    cooldown window.

    This is the home for Gap D's alerting logic. It lives in the cost-model
    module (which owns ``BudgetLine`` and the events) and reaches across to the
    notifications module's :class:`NotificationService` to deliver the in-app
    notification - mirroring how :class:`LabourActualsService` reaches into
    resources. The subscriber below opens its own session and calls
    :meth:`check_and_alert`, swallowing any failure so a notification problem
    never breaks the foreground cost update.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.budget_repo = BudgetLineRepository(session)

    async def _resolve_owner_id(self, project_id: uuid.UUID) -> uuid.UUID | None:
        """Return the project owner's user id, or ``None`` when unavailable."""
        try:
            from app.modules.projects.repository import ProjectRepository

            project = await ProjectRepository(self.session).get_by_id(project_id)
        except Exception:
            return None
        if project is None:
            return None
        return getattr(project, "owner_id", None)

    @staticmethod
    def _cooldown_active(alerted_at: datetime | None, *, now: datetime) -> bool:
        """True when an alert was sent within the cooldown window."""
        if alerted_at is None:
            return False
        # Older rows may carry a naive datetime; treat it as UTC so the
        # comparison never raises on an aware/naive mismatch.
        if alerted_at.tzinfo is None:
            alerted_at = alerted_at.replace(tzinfo=UTC)
        return (now - alerted_at) < _OVERRUN_COOLDOWN

    async def check_and_alert(self, line_id: uuid.UUID, *, now: datetime | None = None) -> bool:
        """Evaluate one budget line and notify the project owner on a breach.

        Returns ``True`` when a notification was sent (and the cooldown stamp
        written), ``False`` otherwise (no threshold, not breached, cooldown
        active, no owner, or line missing). The caller is responsible for
        committing the session.
        """
        now = now or datetime.now(UTC)
        line = await self.budget_repo.get_by_id(line_id)
        if line is None:
            return False

        threshold = getattr(line, "overrun_alert_threshold_pct", "0") or "0"
        if not is_budget_line_overrun(line.planned_amount, line.actual_amount, threshold):
            return False

        if self._cooldown_active(getattr(line, "overrun_alerted_at", None), now=now):
            return False

        # Snapshot everything BEFORE update_fields() expires the ORM row (a
        # later attribute read would re-issue a sync SELECT -> MissingGreenlet).
        project_id = line.project_id
        category = line.category or ""
        currency = line.currency or ""
        planned = str(line.planned_amount)
        actual = str(line.actual_amount)
        # Threshold rendered for the message (strip a trailing ".0").
        try:
            threshold_pct = format(Decimal(str(threshold)).normalize(), "f")
        except (InvalidOperation, ValueError, TypeError):
            threshold_pct = str(threshold)

        owner_id = await self._resolve_owner_id(project_id)
        if owner_id is None:
            # No recipient - do NOT stamp the cooldown so a later owner
            # assignment still gets the first alert.
            return False

        # Deliver the in-app notification (cross-module call, same pattern as
        # the wave-5 subscribers).
        from app.modules.notifications.service import NotificationService

        notif = NotificationService(self.session)
        await notif.create(
            user_id=owner_id,
            notification_type="cost_overrun_alert",
            title_key="notifications.costmodel.overrun_alert.title",
            body_key="notifications.costmodel.overrun_alert.body",
            body_context={
                "category": category or "uncategorised",
                "threshold_pct": threshold_pct,
                "planned": planned,
                "actual": actual,
                "currency": currency,
            },
            entity_type="budget_line",
            entity_id=str(line_id),
            action_url=f"/costmodel?line={line_id}",
        )

        # Stamp the cooldown anchor so a second event inside 24h is a no-op.
        await self.budget_repo.update_fields(line_id, overrun_alerted_at=now)
        logger.info(
            "Cost-overrun alert sent: project=%s line=%s category=%s actual=%s planned=%s @+%s%%",
            project_id,
            line_id,
            category,
            actual,
            planned,
            threshold_pct,
        )
        return True


def _extract_line_id(event: object) -> uuid.UUID | None:
    """Pull a ``budget_line_id`` / ``line_id`` out of an event payload."""
    data = getattr(event, "data", None) or {}
    raw = data.get("budget_line_id") or data.get("line_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


async def _on_budget_line_changed(event: object) -> None:
    """Detached subscriber: alert the project owner when a budget line overruns.

    Bound to both ``costmodel.budget_line.updated`` (manual edits + threshold
    arming) and ``costmodel.budget_line.actual_posted`` (Gap B / labour
    postings, which increment ``actual_amount`` without emitting ``updated``).
    Opens its own session because the publisher is still inside its own request
    transaction, and swallows every exception so an alerting failure never
    breaks the upstream cost update.
    """
    line_id = _extract_line_id(event)
    if line_id is None:
        return

    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            service = CostOverrunAlertService(session)
            await service.check_and_alert(line_id)
            await session.commit()
    except Exception:
        logger.debug("Cost-overrun alert check failed for line=%s", line_id, exc_info=True)


# Bind the overrun subscriber at import time (same rationale as the labour
# subscriber above). Guard against double-registration on repeated imports.
for _overrun_event in ("costmodel.budget_line.updated", "costmodel.budget_line.actual_posted"):
    if _on_budget_line_changed not in event_bus._handlers.get(_overrun_event, []):
        event_bus.subscribe(_overrun_event, _on_budget_line_changed)
