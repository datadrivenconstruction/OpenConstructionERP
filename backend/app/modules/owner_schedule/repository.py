# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule data access over the module's own tables."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.owner_schedule.models import OwnerSchedule, OwnerScheduleItem, OwnerScheduleProfile


class OwnerScheduleRepository:
    """Queries over schedules, their items and saved profiles."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_boq(self, boq_id: uuid.UUID) -> OwnerSchedule | None:
        rows = await self.session.execute(select(OwnerSchedule).where(OwnerSchedule.boq_id == boq_id))
        return rows.scalar_one_or_none()

    async def items(self, schedule_id: uuid.UUID) -> list[OwnerScheduleItem]:
        rows = await self.session.execute(
            select(OwnerScheduleItem)
            .where(OwnerScheduleItem.schedule_id == schedule_id)
            .order_by(OwnerScheduleItem.row_index)
        )
        return list(rows.scalars())

    async def user_profiles(self) -> list[OwnerScheduleProfile]:
        rows = await self.session.execute(select(OwnerScheduleProfile).order_by(OwnerScheduleProfile.name))
        return list(rows.scalars())

    async def user_profile(self, key: str) -> OwnerScheduleProfile | None:
        rows = await self.session.execute(select(OwnerScheduleProfile).where(OwnerScheduleProfile.key == key))
        return rows.scalar_one_or_none()
