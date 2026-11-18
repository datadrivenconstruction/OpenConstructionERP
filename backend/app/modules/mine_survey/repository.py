# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the mine survey. Writes only ``oe_mine_*``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mine_survey.models import MinePeriod, MinePeriodEntry, MineUnit


class MineRepository:
    """Queries behind the mine survey service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: Any) -> None:
        self.session.add(obj)
        await self.session.flush()

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    # ── Units ──────────────────────────────────────────────────────────────

    async def list_units(self, project_id: uuid.UUID) -> list[MineUnit]:
        rows = await self.session.execute(
            select(MineUnit).where(MineUnit.project_id == project_id).order_by(MineUnit.code)
        )
        return list(rows.scalars().all())

    async def get_unit(self, unit_id: uuid.UUID) -> MineUnit | None:
        return await self.session.get(MineUnit, unit_id)

    async def unit_by_name(self, project_id: uuid.UUID, name: str) -> MineUnit | None:
        rows = await self.session.execute(
            select(MineUnit).where(MineUnit.project_id == project_id, func.lower(MineUnit.name) == name.strip().lower())
        )
        return rows.scalars().first()

    async def unit_codes(self, project_id: uuid.UUID) -> list[str]:
        rows = await self.session.execute(select(MineUnit.code).where(MineUnit.project_id == project_id))
        return [str(c) for (c,) in rows.all()]

    async def entry_counts_by_unit(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        rows = await self.session.execute(
            select(MinePeriodEntry.unit_id, func.count())
            .where(MinePeriodEntry.project_id == project_id)
            .group_by(MinePeriodEntry.unit_id)
        )
        return {u: int(n) for u, n in rows.all()}

    # ── Periods ────────────────────────────────────────────────────────────

    async def list_periods(self, project_id: uuid.UUID) -> list[MinePeriod]:
        rows = await self.session.execute(
            select(MinePeriod).where(MinePeriod.project_id == project_id).order_by(MinePeriod.period_start.desc())
        )
        return list(rows.scalars().all())

    async def get_period(self, period_id: uuid.UUID) -> MinePeriod | None:
        return await self.session.get(MinePeriod, period_id)

    async def period_by_label(self, project_id: uuid.UUID, label: str) -> MinePeriod | None:
        rows = await self.session.execute(
            select(MinePeriod).where(MinePeriod.project_id == project_id, MinePeriod.label == label)
        )
        return rows.scalars().first()

    async def entry_counts_by_period(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        rows = await self.session.execute(
            select(MinePeriodEntry.period_id, func.count())
            .where(MinePeriodEntry.project_id == project_id)
            .group_by(MinePeriodEntry.period_id)
        )
        return {p: int(n) for p, n in rows.all()}

    # ── Entries ────────────────────────────────────────────────────────────

    async def entries_of(self, period_id: uuid.UUID) -> list[MinePeriodEntry]:
        rows = await self.session.execute(
            select(MinePeriodEntry).where(MinePeriodEntry.period_id == period_id).order_by(MinePeriodEntry.created_at)
        )
        return list(rows.scalars().all())

    async def get_entry(self, entry_id: uuid.UUID) -> MinePeriodEntry | None:
        return await self.session.get(MinePeriodEntry, entry_id)

    async def entry_for(self, period_id: uuid.UUID, unit_id: uuid.UUID) -> MinePeriodEntry | None:
        rows = await self.session.execute(
            select(MinePeriodEntry).where(MinePeriodEntry.period_id == period_id, MinePeriodEntry.unit_id == unit_id)
        )
        return rows.scalars().first()

    # ── Other modules, read only ───────────────────────────────────────────

    async def user_name(self, user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return ""
        try:
            from app.modules.users.models import User  # noqa: PLC0415
        except ImportError:  # pragma: no cover - users is core
            return ""
        row = (await self.session.execute(select(User.full_name, User.email).where(User.id == user_id))).first()
        if row is None:
            return ""
        return str(row[0] or row[1] or "")
