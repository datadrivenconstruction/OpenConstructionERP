# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site-supervision data-access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_supervision.models import SupervisionEntry, SupervisionVisit


class SupervisionRepository:
    """Data access for supervision visits and entries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Visits ──────────────────────────────────────────────────────────

    async def get_visit(self, visit_id: uuid.UUID) -> SupervisionVisit | None:
        return await self.session.get(SupervisionVisit, visit_id)

    async def list_visits(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        discipline: str | None = None,
    ) -> list[SupervisionVisit]:
        stmt = select(SupervisionVisit).where(SupervisionVisit.project_id == project_id)
        if status is not None:
            stmt = stmt.where(SupervisionVisit.status == status)
        if discipline is not None:
            stmt = stmt.where(SupervisionVisit.discipline == discipline)
        # Most recent activity first: newest actual date, then newest planned.
        stmt = stmt.order_by(
            SupervisionVisit.actual_date.is_(None),
            SupervisionVisit.actual_date.desc(),
            SupervisionVisit.planned_date.desc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_visit(self, visit: SupervisionVisit) -> SupervisionVisit:
        self.session.add(visit)
        await self.session.flush()
        return visit

    async def delete_visit(self, visit_id: uuid.UUID) -> None:
        row = await self.get_visit(visit_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    # ── Entries ─────────────────────────────────────────────────────────

    async def get_entry(self, entry_id: uuid.UUID) -> SupervisionEntry | None:
        return await self.session.get(SupervisionEntry, entry_id)

    async def list_entries_for_visit(self, visit_id: uuid.UUID) -> list[SupervisionEntry]:
        stmt = (
            select(SupervisionEntry)
            .where(SupervisionEntry.visit_id == visit_id)
            .order_by(SupervisionEntry.ordinal.asc(), SupervisionEntry.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_entries_for_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        status: str | None = None,
    ) -> list[SupervisionEntry]:
        stmt = select(SupervisionEntry).where(SupervisionEntry.project_id == project_id)
        if category is not None:
            stmt = stmt.where(SupervisionEntry.category == category)
        if status is not None:
            stmt = stmt.where(SupervisionEntry.status == status)
        stmt = stmt.order_by(SupervisionEntry.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_entry(self, entry: SupervisionEntry) -> SupervisionEntry:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def delete_entry(self, entry_id: uuid.UUID) -> None:
        row = await self.get_entry(entry_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()


__all__ = ["SupervisionRepository"]
