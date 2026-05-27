# OpenConstructionERP — DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Progress tracking data access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.models import ProgressEntry, ProgressPlan


class ProgressRepository:
    """Data access for ProgressEntry and ProgressPlan models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── ProgressEntry ────────────────────────────────────────────────────

    async def create_entry(self, entry: ProgressEntry) -> ProgressEntry:
        """Insert a new progress entry."""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_entry(self, entry_id: uuid.UUID) -> ProgressEntry | None:
        return await self.session.get(ProgressEntry, entry_id)

    async def list_entries_for_project(
        self,
        project_id: uuid.UUID,
        *,
        boq_position_id: uuid.UUID | None = None,
        period_label: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ProgressEntry]:
        """Return progress entries, optionally filtered by position or period."""
        stmt = select(ProgressEntry).where(ProgressEntry.project_id == project_id)
        if boq_position_id is not None:
            stmt = stmt.where(ProgressEntry.boq_position_id == boq_position_id)
        if period_label is not None:
            stmt = stmt.where(ProgressEntry.period_label == period_label)
        stmt = stmt.order_by(ProgressEntry.recorded_at.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def latest_pct_for_positions(
        self,
        project_id: uuid.UUID,
        position_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]:
        """Return the most-recent percent_complete for each requested position.

        Uses a correlated MAX(recorded_at) subquery so we get exactly one row
        per position without loading all history.
        """
        if not position_ids:
            return {}

        # Subquery: latest recorded_at per position
        sub = (
            select(
                ProgressEntry.boq_position_id,
                func.max(ProgressEntry.recorded_at).label("max_ra"),
            )
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.boq_position_id.in_(position_ids),
            )
            .group_by(ProgressEntry.boq_position_id)
            .subquery()
        )

        stmt = select(ProgressEntry.boq_position_id, ProgressEntry.percent_complete).join(
            sub,
            (ProgressEntry.boq_position_id == sub.c.boq_position_id) & (ProgressEntry.recorded_at == sub.c.max_ra),
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: float(row[1]) for row in rows}

    async def entries_grouped_by_period(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID | None = None,
    ) -> list[tuple[str, float]]:
        """Return (period_label, max_pct) pairs ordered by period_label.

        For each period we take the MAXIMUM percent_complete recorded — this
        handles multiple same-period entries by using the most optimistic value.
        """
        stmt = select(
            ProgressEntry.period_label,
            func.max(ProgressEntry.percent_complete),
        ).where(ProgressEntry.project_id == project_id)
        if boq_position_id is not None:
            stmt = stmt.where(ProgressEntry.boq_position_id == boq_position_id)
        stmt = stmt.group_by(ProgressEntry.period_label).order_by(ProgressEntry.period_label.asc())
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], float(row[1])) for row in rows]

    # ── ProgressPlan ─────────────────────────────────────────────────────

    async def upsert_plan(
        self,
        project_id: uuid.UUID,
        period_label: str,
        planned_pct: float,
        notes: str | None = None,
    ) -> ProgressPlan:
        """Insert or update a plan point for (project, period_label)."""
        stmt = select(ProgressPlan).where(
            ProgressPlan.project_id == project_id,
            ProgressPlan.period_label == period_label,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.planned_pct = planned_pct  # type: ignore[assignment]
            if notes is not None:
                existing.notes = notes  # type: ignore[assignment]
            await self.session.flush()
            return existing

        plan = ProgressPlan(
            project_id=project_id,
            period_label=period_label,
            planned_pct=planned_pct,
            notes=notes,
        )
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def list_plan(self, project_id: uuid.UUID) -> list[ProgressPlan]:
        """Return all plan points ordered by period_label."""
        stmt = (
            select(ProgressPlan).where(ProgressPlan.project_id == project_id).order_by(ProgressPlan.period_label.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
