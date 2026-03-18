"""5D Cost Model service — business logic for EVM, budgets, and cash flow.

Stateless service layer.  Handles:
- EVM snapshot creation and S-curve data
- Dashboard KPIs aggregation
- Budget generation from BOQ positions
- Cash flow generation from budget schedule
- Event publishing for inter-module communication
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.costmodel.models import BudgetLine, CashFlow, CostSnapshot
from app.modules.costmodel.repository import (
    BudgetLineRepository,
    CashFlowRepository,
    SnapshotRepository,
)
from app.modules.costmodel.schemas import (
    BudgetCategoryRow,
    BudgetLineCreate,
    BudgetLineUpdate,
    BudgetSummary,
    CashFlowCreate,
    CashFlowData,
    CashFlowPeriod,
    DashboardResponse,
    SCurveData,
    SCurvePeriod,
    SnapshotCreate,
    SnapshotResponse,
    SnapshotUpdate,
)

logger = logging.getLogger(__name__)


def _str_to_float(value: str | None) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_divide(numerator: float, denominator: float) -> float:
    """Safely divide two floats, returning 0.0 on zero denominator."""
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _variance_pct(planned: float, forecast: float) -> float:
    """Calculate variance percentage: (planned - forecast) / planned * 100."""
    if planned == 0.0:
        return 0.0
    return round((planned - forecast) / planned * 100.0, 2)


class CostModelService:
    """Business logic for 5D Cost Model operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.snapshot_repo = SnapshotRepository(session)
        self.budget_repo = BudgetLineRepository(session)
        self.cashflow_repo = CashFlowRepository(session)

    # ── Snapshot operations ────────────────────────────────────────────────

    async def create_snapshot(
        self, data: SnapshotCreate
    ) -> CostSnapshot:
        """Create a monthly EVM snapshot.

        Computes SPI and CPI from the provided planned/earned/actual values
        if they are not explicitly set.

        Args:
            data: Snapshot creation payload.

        Returns:
            The newly created snapshot.
        """
        spi = data.spi
        cpi = data.cpi

        # Auto-compute indices if not provided (left at default 0)
        if spi == 0.0 and data.planned_cost > 0.0:
            spi = round(_safe_divide(data.earned_value, data.planned_cost), 4)
        if cpi == 0.0 and data.actual_cost > 0.0:
            cpi = round(_safe_divide(data.earned_value, data.actual_cost), 4)

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

        await event_bus.publish(
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

    async def update_snapshot(
        self, snapshot_id: uuid.UUID, data: SnapshotUpdate
    ) -> CostSnapshot:
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

        total_budget = _str_to_float(aggregates["total_planned"])
        total_committed = _str_to_float(aggregates["total_committed"])
        total_actual = _str_to_float(aggregates["total_actual"])
        total_forecast = _str_to_float(aggregates["total_forecast"])
        variance = total_budget - total_forecast

        # Get SPI and CPI from latest snapshot
        spi = 0.0
        cpi = 0.0
        latest = await self.snapshot_repo.get_latest_for_project(project_id)
        if latest is not None:
            spi = _str_to_float(latest.spi)
            cpi = _str_to_float(latest.cpi)

        budget_status = "on_budget" if variance >= 0 else "over_budget"

        return DashboardResponse(
            total_budget=round(total_budget, 2),
            total_committed=round(total_committed, 2),
            total_actual=round(total_actual, 2),
            total_forecast=round(total_forecast, 2),
            variance=round(variance, 2),
            spi=round(spi, 4),
            cpi=round(cpi, 4),
            status=budget_status,
        )

    # ── S-Curve ────────────────────────────────────────────────────────────

    async def get_s_curve(self, project_id: uuid.UUID) -> SCurveData:
        """Build S-curve time series from EVM snapshots.

        Returns cumulative planned, earned, and actual values per period,
        ordered chronologically.

        Args:
            project_id: Target project.

        Returns:
            SCurveData with list of period data points.
        """
        snapshots, _ = await self.snapshot_repo.list_for_project(
            project_id, limit=1000
        )

        cumulative_planned = 0.0
        cumulative_earned = 0.0
        cumulative_actual = 0.0

        periods: list[SCurvePeriod] = []
        for snap in snapshots:
            cumulative_planned += _str_to_float(snap.planned_cost)
            cumulative_earned += _str_to_float(snap.earned_value)
            cumulative_actual += _str_to_float(snap.actual_cost)

            periods.append(
                SCurvePeriod(
                    period=snap.period,
                    planned=round(cumulative_planned, 2),
                    earned=round(cumulative_earned, 2),
                    actual=round(cumulative_actual, 2),
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
        entries, _ = await self.cashflow_repo.list_for_project(
            project_id, limit=1000
        )

        periods: list[CashFlowPeriod] = []
        for entry in entries:
            inflow = _str_to_float(entry.actual_inflow) or _str_to_float(
                entry.planned_inflow
            )
            outflow = _str_to_float(entry.actual_outflow) or _str_to_float(
                entry.planned_outflow
            )

            periods.append(
                CashFlowPeriod(
                    period=entry.period,
                    inflow=round(inflow, 2),
                    outflow=round(outflow, 2),
                    cumulative_planned=round(
                        _str_to_float(entry.cumulative_planned), 2
                    ),
                    cumulative_actual=round(
                        _str_to_float(entry.cumulative_actual), 2
                    ),
                )
            )

        return CashFlowData(periods=periods)

    async def create_cash_flow_entry(
        self, data: CashFlowCreate
    ) -> CashFlow:
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

        await event_bus.publish(
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

    async def get_budget_summary(
        self, project_id: uuid.UUID
    ) -> BudgetSummary:
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
                    variance_pct=_variance_pct(planned, forecast),
                )
            )

        return BudgetSummary(by_category=categories)

    async def list_budget_lines(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BudgetLine], int]:
        """List detailed budget lines for a project."""
        return await self.budget_repo.list_for_project(
            project_id, category=category, offset=offset, limit=limit
        )

    async def create_budget_line(
        self, data: BudgetLineCreate
    ) -> BudgetLine:
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

        await event_bus.publish(
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

    async def update_budget_line(
        self, line_id: uuid.UUID, data: BudgetLineUpdate
    ) -> BudgetLine:
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

            await event_bus.publish(
                "costmodel.budget_line.updated",
                {
                    "line_id": str(line_id),
                    "project_id": str(line.project_id),
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

        await event_bus.publish(
            "costmodel.budget_line.deleted",
            {"line_id": str(line_id), "project_id": project_id},
            source_module="oe_costmodel",
        )

        logger.info("Budget line deleted: %s", line_id)

    # ── Generation helpers ─────────────────────────────────────────────────

    async def generate_budget_from_boq(
        self, project_id: uuid.UUID, boq_id: uuid.UUID
    ) -> list[BudgetLine]:
        """Auto-generate budget lines from BOQ positions.

        Each BOQ position becomes a budget line with planned_amount = position total.
        Existing budget lines for the project are NOT deleted — new lines are appended.

        Args:
            project_id: Target project.
            boq_id: Source BOQ to generate budget from.

        Returns:
            List of newly created budget lines.
        """
        from app.modules.boq.repository import PositionRepository

        position_repo = PositionRepository(self.session)
        positions, _ = await position_repo.list_for_boq(boq_id, limit=10000)

        if not positions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No positions found in the specified BOQ",
            )

        lines: list[BudgetLine] = []
        for pos in positions:
            total = _str_to_float(pos.total)
            line = BudgetLine(
                project_id=project_id,
                boq_position_id=pos.id,
                category="material",  # Default; user can reclassify later
                description=f"{pos.ordinal} — {pos.description[:200]}",
                planned_amount=str(total),
                committed_amount="0",
                actual_amount="0",
                forecast_amount=str(total),
                currency="",
            )
            lines.append(line)

        created = await self.budget_repo.bulk_create(lines)

        await event_bus.publish(
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

    async def generate_cash_flow_from_schedule(
        self, project_id: uuid.UUID
    ) -> list[CashFlow]:
        """Generate cash flow entries by spreading budget line amounts across their schedule.

        For budget lines that have period_start and period_end, the planned_amount
        is evenly distributed across the months in that range.  Lines without a
        schedule are placed into a single 'unscheduled' entry.

        Args:
            project_id: Target project.

        Returns:
            List of newly created cash flow entries.
        """
        budget_lines, _ = await self.budget_repo.list_for_project(
            project_id, limit=10000
        )

        if not budget_lines:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No budget lines found for the project",
            )

        # Aggregate outflows per period
        period_outflows: dict[str, Decimal] = {}

        for bl in budget_lines:
            amount = Decimal(str(_str_to_float(bl.planned_amount)))
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
                # No schedule — use a generic unscheduled bucket
                period_outflows["unscheduled"] = (
                    period_outflows.get("unscheduled", Decimal("0")) + amount
                )

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

        await event_bus.publish(
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
