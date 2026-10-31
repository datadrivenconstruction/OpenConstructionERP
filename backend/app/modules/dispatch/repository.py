# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board data access. Every board query is bounded by day and indexed."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dispatch.models import (
    DispatchCrew,
    DispatchLocation,
    DispatchPlacement,
    DispatchScheduledMove,
    DispatchViewPref,
)


class DispatchRepository:
    """Queries over locations, crews, placements, scheduled moves and view preferences."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: object) -> None:
        self.session.add(obj)
        await self.session.flush()

    # Locations
    async def list_locations(self, *, include_inactive: bool = False) -> list[DispatchLocation]:
        stmt = select(DispatchLocation)
        if not include_inactive:
            stmt = stmt.where(DispatchLocation.is_active.is_(True))
        stmt = stmt.order_by(DispatchLocation.sort_order, DispatchLocation.name).limit(500)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_location(self, location_id: uuid.UUID) -> DispatchLocation | None:
        return await self.session.get(DispatchLocation, location_id)

    # Crews
    async def list_crews(self, *, limit: int = 200, offset: int = 0) -> list[DispatchCrew]:
        stmt = (
            select(DispatchCrew)
            .where(DispatchCrew.is_active.is_(True))
            .order_by(DispatchCrew.name)
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def crews_by_ids(self, ids: set[str]) -> list[DispatchCrew]:
        uuids = [uuid.UUID(i) for i in ids if _is_uuid(i)]
        if not uuids:
            return []
        return list((await self.session.execute(select(DispatchCrew).where(DispatchCrew.id.in_(uuids)))).scalars())

    async def get_crew(self, crew_id: uuid.UUID) -> DispatchCrew | None:
        return await self.session.get(DispatchCrew, crew_id)

    # Placements
    async def placements_between(
        self, start: date, end: date, *, location_ids: list[uuid.UUID] | None = None, limit: int = 5000
    ) -> list[DispatchPlacement]:
        stmt = select(DispatchPlacement).where(DispatchPlacement.day >= start, DispatchPlacement.day <= end)
        if location_ids is not None:
            stmt = stmt.where(DispatchPlacement.location_id.in_(location_ids))
        stmt = stmt.order_by(DispatchPlacement.day, DispatchPlacement.start_time).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def placements_on(self, day: date) -> list[DispatchPlacement]:
        return await self.placements_between(day, day)

    async def placements_by_ids(self, ids: list[uuid.UUID]) -> list[DispatchPlacement]:
        if not ids:
            return []
        stmt = select(DispatchPlacement).where(DispatchPlacement.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_placements(self, ids: list[uuid.UUID]) -> int:
        if not ids:
            return 0
        res = await self.session.execute(delete(DispatchPlacement).where(DispatchPlacement.id.in_(ids)))
        await self.session.flush()
        return int(res.rowcount or 0)

    # Scheduled moves
    async def list_moves(
        self, *, status: str | None = None, start: date | None = None, end: date | None = None, limit: int = 500
    ) -> list[DispatchScheduledMove]:
        stmt = select(DispatchScheduledMove)
        if status:
            stmt = stmt.where(DispatchScheduledMove.status == status)
        if start:
            stmt = stmt.where(DispatchScheduledMove.effective_date >= start)
        if end:
            stmt = stmt.where(DispatchScheduledMove.effective_date <= end)
        stmt = stmt.order_by(DispatchScheduledMove.effective_date, DispatchScheduledMove.created_at).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_move(self, move_id: uuid.UUID) -> DispatchScheduledMove | None:
        return await self.session.get(DispatchScheduledMove, move_id)

    # View preference
    async def get_pref(self, user_id: uuid.UUID) -> DispatchViewPref | None:
        stmt = select(DispatchViewPref).where(DispatchViewPref.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True
