"""5D Cost Model data access layer.

All database queries for cost snapshots, budget lines, and cash flow entries
live here.  No business logic — pure data access.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine, CashFlow, CostSnapshot


# ── CostSnapshot repository ─────────────────────────────────────────────────


class SnapshotRepository:
    """Data access for CostSnapshot model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, snapshot_id: uuid.UUID) -> CostSnapshot | None:
        """Get snapshot by ID."""
        return await self.session.get(CostSnapshot, snapshot_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        period_from: str | None = None,
        period_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CostSnapshot], int]:
        """List snapshots for a project, optionally filtered by period range.

        Args:
            project_id: Target project.
            period_from: Inclusive lower bound (YYYY-MM).
            period_to: Inclusive upper bound (YYYY-MM).
            offset: Pagination offset.
            limit: Pagination limit.

        Returns:
            Tuple of (snapshots, total_count).
        """
        base = select(CostSnapshot).where(CostSnapshot.project_id == project_id)

        if period_from is not None:
            base = base.where(CostSnapshot.period >= period_from)
        if period_to is not None:
            base = base.where(CostSnapshot.period <= period_to)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(CostSnapshot.period.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        snapshots = list(result.scalars().all())

        return snapshots, total

    async def get_latest_for_project(
        self, project_id: uuid.UUID
    ) -> CostSnapshot | None:
        """Get the most recent snapshot for a project (by period desc)."""
        stmt = (
            select(CostSnapshot)
            .where(CostSnapshot.project_id == project_id)
            .order_by(CostSnapshot.period.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, snapshot: CostSnapshot) -> CostSnapshot:
        """Insert a new snapshot."""
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def update_fields(self, snapshot_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a snapshot."""
        stmt = update(CostSnapshot).where(CostSnapshot.id == snapshot_id).values(**fields)
        await self.session.execute(stmt)

    async def delete(self, snapshot_id: uuid.UUID) -> None:
        """Delete a snapshot."""
        stmt = delete(CostSnapshot).where(CostSnapshot.id == snapshot_id)
        await self.session.execute(stmt)


# ── BudgetLine repository ───────────────────────────────────────────────────


class BudgetLineRepository:
    """Data access for BudgetLine model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, line_id: uuid.UUID) -> BudgetLine | None:
        """Get budget line by ID."""
        return await self.session.get(BudgetLine, line_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BudgetLine], int]:
        """List budget lines for a project with optional category filter.

        Args:
            project_id: Target project.
            category: Optional category filter (e.g. 'material').
            offset: Pagination offset.
            limit: Pagination limit.

        Returns:
            Tuple of (budget_lines, total_count).
        """
        base = select(BudgetLine).where(BudgetLine.project_id == project_id)

        if category is not None:
            base = base.where(BudgetLine.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BudgetLine.category, BudgetLine.created_at).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        lines = list(result.scalars().all())

        return lines, total

    async def aggregate_by_project(
        self, project_id: uuid.UUID
    ) -> dict[str, str]:
        """Aggregate budget line totals for a project.

        Returns:
            Dict with keys: total_planned, total_committed, total_actual, total_forecast
            (all as string sums from the database).
        """
        from sqlalchemy import Float, cast

        stmt = select(
            func.coalesce(func.sum(cast(BudgetLine.planned_amount, Float)), 0),
            func.coalesce(func.sum(cast(BudgetLine.committed_amount, Float)), 0),
            func.coalesce(func.sum(cast(BudgetLine.actual_amount, Float)), 0),
            func.coalesce(func.sum(cast(BudgetLine.forecast_amount, Float)), 0),
        ).where(BudgetLine.project_id == project_id)

        result = await self.session.execute(stmt)
        row = result.one()

        return {
            "total_planned": str(row[0]),
            "total_committed": str(row[1]),
            "total_actual": str(row[2]),
            "total_forecast": str(row[3]),
        }

    async def aggregate_by_category(
        self, project_id: uuid.UUID
    ) -> list[dict[str, str]]:
        """Aggregate budget lines grouped by category.

        Returns:
            List of dicts with keys: category, planned, committed, actual, forecast.
        """
        from sqlalchemy import Float, cast

        stmt = (
            select(
                BudgetLine.category,
                func.coalesce(func.sum(cast(BudgetLine.planned_amount, Float)), 0),
                func.coalesce(func.sum(cast(BudgetLine.committed_amount, Float)), 0),
                func.coalesce(func.sum(cast(BudgetLine.actual_amount, Float)), 0),
                func.coalesce(func.sum(cast(BudgetLine.forecast_amount, Float)), 0),
            )
            .where(BudgetLine.project_id == project_id)
            .group_by(BudgetLine.category)
            .order_by(BudgetLine.category)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            {
                "category": row[0],
                "planned": str(row[1]),
                "committed": str(row[2]),
                "actual": str(row[3]),
                "forecast": str(row[4]),
            }
            for row in rows
        ]

    async def create(self, line: BudgetLine) -> BudgetLine:
        """Insert a new budget line."""
        self.session.add(line)
        await self.session.flush()
        return line

    async def bulk_create(self, lines: list[BudgetLine]) -> list[BudgetLine]:
        """Insert multiple budget lines at once."""
        self.session.add_all(lines)
        await self.session.flush()
        return lines

    async def update_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a budget line."""
        stmt = update(BudgetLine).where(BudgetLine.id == line_id).values(**fields)
        await self.session.execute(stmt)

    async def delete(self, line_id: uuid.UUID) -> None:
        """Delete a budget line."""
        stmt = delete(BudgetLine).where(BudgetLine.id == line_id)
        await self.session.execute(stmt)

    async def delete_for_project(self, project_id: uuid.UUID) -> int:
        """Delete all budget lines for a project. Returns deleted count."""
        count_stmt = select(func.count()).where(BudgetLine.project_id == project_id)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = delete(BudgetLine).where(BudgetLine.project_id == project_id)
        await self.session.execute(stmt)
        return total


# ── CashFlow repository ─────────────────────────────────────────────────────


class CashFlowRepository:
    """Data access for CashFlow model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entry_id: uuid.UUID) -> CashFlow | None:
        """Get cash flow entry by ID."""
        return await self.session.get(CashFlow, entry_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CashFlow], int]:
        """List cash flow entries for a project.

        Args:
            project_id: Target project.
            category: Optional category filter.
            offset: Pagination offset.
            limit: Pagination limit.

        Returns:
            Tuple of (entries, total_count).
        """
        base = select(CashFlow).where(CashFlow.project_id == project_id)

        if category is not None:
            base = base.where(CashFlow.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(CashFlow.period.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        entries = list(result.scalars().all())

        return entries, total

    async def create(self, entry: CashFlow) -> CashFlow:
        """Insert a new cash flow entry."""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def bulk_create(self, entries: list[CashFlow]) -> list[CashFlow]:
        """Insert multiple cash flow entries at once."""
        self.session.add_all(entries)
        await self.session.flush()
        return entries

    async def update_fields(self, entry_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a cash flow entry."""
        stmt = update(CashFlow).where(CashFlow.id == entry_id).values(**fields)
        await self.session.execute(stmt)

    async def delete(self, entry_id: uuid.UUID) -> None:
        """Delete a cash flow entry."""
        stmt = delete(CashFlow).where(CashFlow.id == entry_id)
        await self.session.execute(stmt)

    async def delete_for_project(self, project_id: uuid.UUID) -> int:
        """Delete all cash flow entries for a project. Returns deleted count."""
        count_stmt = select(func.count()).where(CashFlow.project_id == project_id)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = delete(CashFlow).where(CashFlow.project_id == project_id)
        await self.session.execute(stmt)
        return total
