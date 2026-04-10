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
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


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
    EVMResponse,
    SCurveData,
    SCurvePeriod,
    SnapshotCreate,
    SnapshotUpdate,
    WhatIfAdjustments,
    WhatIfResult,
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

    async def _get_project_currency(self, project_id: uuid.UUID) -> str:
        """Get the currency from the project settings. Defaults to EUR."""
        try:
            from app.modules.projects.repository import ProjectRepository

            repo = ProjectRepository(self.session)
            project = await repo.get_by_id(project_id)
            return project.currency if project and project.currency else "EUR"
        except Exception:
            return "EUR"

    # ── Snapshot operations ────────────────────────────────────────────────

    async def create_snapshot(self, data: SnapshotCreate) -> CostSnapshot:
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

        variance_pct = _variance_pct(total_budget, total_forecast) if total_budget > 0 else 0.0

        return DashboardResponse(
            total_budget=round(total_budget, 2),
            total_committed=round(total_committed, 2),
            total_actual=round(total_actual, 2),
            total_forecast=round(total_forecast, 2),
            variance=round(variance, 2),
            variance_pct=round(variance_pct, 2),
            spi=round(spi, 4),
            cpi=round(cpi, 4),
            status=budget_status,
            currency=await self._get_project_currency(project_id),
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
        snapshots, _ = await self.snapshot_repo.list_for_project(project_id, limit=1000)

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

    # ── EVM Calculations ──────────────────────────────────────────────────

    async def calculate_evm(self, project_id: uuid.UUID) -> EVMResponse:
        """Calculate real Earned Value Management metrics from schedule progress and budget.

        Reads schedule activities for progress percentage and budget lines for planned
        and actual values.  Computes all standard EVM indices.

        Algorithm:
            1. BAC = sum of planned_amount across all budget lines
            2. AC  = sum of actual_amount across all budget lines
            3. time_elapsed% = computed from project schedule start/end vs today
            4. schedule_progress% = weighted average of activity progress_pct
               (weighted by planned_amount of linked budget lines)
            5. PV  = BAC * time_elapsed%
            6. EV  = BAC * schedule_progress%
            7. Derived indices: SV, CV, SPI, CPI, EAC, ETC, VAC, TCPI

        Known limitation (v1.3.x):
            PV is an approximation: ``BAC × time_elapsed%`` rather than a proper
            time-phased baseline. When a project has not started yet (``time_elapsed%``
            ~ 0) but activities already report progress, SPI = EV / PV explodes.
            To prevent mathematically impossible values we clamp:
                - ``pv`` to a minimum of ``1% × BAC`` (avoids divide-by-near-zero)
                - ``spi`` to the ``[0.0, 5.0]`` range
            and set ``spi_capped=True`` so the UI can label the figure as approximate.
            TODO (v1.4): replace with a proper time-phased PV computed from
            ``BudgetLine`` + ``Activity`` planned dates (see audit notes, Option A).

        Args:
            project_id: Target project.

        Returns:
            EVMResponse with all computed EVM metrics.
        """
        from datetime import date

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

        # ── Step 2: Read schedule activities for progress ──────────────────
        schedule_repo = ScheduleRepository(self.session)
        schedules, _ = await schedule_repo.list_for_project(project_id, limit=50)

        time_elapsed_pct = 0.0
        schedule_progress_pct = 0.0

        if schedules:
            # Use the first (primary) schedule for time elapsed calculation
            primary_schedule = schedules[0]
            today = date.today()

            # Compute time_elapsed_pct from schedule dates
            if primary_schedule.start_date and primary_schedule.end_date:
                try:
                    start = date.fromisoformat(primary_schedule.start_date[:10])
                    end = date.fromisoformat(primary_schedule.end_date[:10])
                    total_days = (end - start).days
                    if total_days > 0:
                        elapsed_days = (today - start).days
                        time_elapsed_pct = max(0.0, min(100.0, (elapsed_days / total_days) * 100.0))
                except (ValueError, TypeError):
                    pass

            # Compute weighted schedule progress from all activities
            activity_repo = ActivityRepository(self.session)
            total_weighted_progress = 0.0
            total_weight = 0.0

            # Build lookup: budget lines keyed by activity_id (hoisted out of the
            # per-schedule loop — these lines are project-scoped, not schedule-scoped,
            # so fetching once avoids an N+1 query).
            budget_lines, _ = await self.budget_repo.list_for_project(project_id, limit=10000)
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
            # No schedule — fall back to using time from latest snapshot period
            latest = await self.snapshot_repo.get_latest_for_project(project_id)
            if latest is not None:
                time_elapsed_pct = 50.0  # conservative fallback
                # Use latest snapshot EV/PV as approximation
                pv_snap = _str_to_float(latest.planned_cost)
                ev_snap = _str_to_float(latest.earned_value)
                if pv_snap > 0.0:
                    schedule_progress_pct = (ev_snap / bac) * 100.0

        # ── Step 3: Compute EVM values ─────────────────────────────────────
        # PV is an approximation (BAC × time_elapsed%). See the function
        # docstring for limitations. We clamp PV to a minimum of 1% × BAC so
        # SPI never explodes toward infinity when the project has not really
        # started yet but activities report nominal progress.
        raw_pv = bac * (time_elapsed_pct / 100.0)
        pv_floor = bac * 0.01  # 1% of BAC — prevents divide-by-near-zero
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
        tcpi = _safe_divide(bac - ev, bac - ac)

        # ── Step 4: Determine project health status ────────────────────────
        if spi >= 0.95 and cpi >= 0.95:
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
            tcpi=round(tcpi, 4),
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
        from datetime import date

        today = date.today()
        period = f"{today.year:04d}-{today.month:02d}"

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
        # Pick the most recently updated BOQ — that's the one the user is
        # actively working on. position_count is computed lazily so don't
        # rely on it here.
        sorted_boqs = sorted(boqs, key=lambda b: b.updated_at, reverse=True)
        return sorted_boqs[0].id

    async def generate_budget_from_boq(self, project_id: uuid.UUID, boq_id: uuid.UUID) -> list[BudgetLine]:
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
                period_outflows["unscheduled"] = period_outflows.get("unscheduled", Decimal("0")) + amount

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
