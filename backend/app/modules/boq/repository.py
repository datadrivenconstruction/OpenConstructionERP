"""BOQ data access layer.

All database queries for BOQs and positions live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position


class BOQRepository:
    """Data access for BOQ model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, boq_id: uuid.UUID) -> BOQ | None:
        """Get BOQ by ID."""
        return await self.session.get(BOQ, boq_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQ], int]:
        """List BOQs for a project with pagination. Returns (boqs, total_count)."""
        base = select(BOQ).where(BOQ.project_id == project_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(BOQ.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        boqs = list(result.scalars().all())

        return boqs, total

    async def create(self, boq: BOQ) -> BOQ:
        """Insert a new BOQ."""
        self.session.add(boq)
        await self.session.flush()
        return boq

    async def update_fields(self, boq_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a BOQ."""
        stmt = update(BOQ).where(BOQ.id == boq_id).values(**fields)
        await self.session.execute(stmt)

    async def delete(self, boq_id: uuid.UUID) -> None:
        """Delete a BOQ and all its positions (via CASCADE)."""
        stmt = delete(BOQ).where(BOQ.id == boq_id)
        await self.session.execute(stmt)


class PositionRepository:
    """Data access for Position model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, position_id: uuid.UUID) -> Position | None:
        """Get position by ID."""
        return await self.session.get(Position, position_id)

    async def list_for_boq(
        self,
        boq_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> tuple[list[Position], int]:
        """List positions for a BOQ ordered by sort_order. Returns (positions, total)."""
        base = select(Position).where(Position.boq_id == boq_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch ordered by sort_order, then ordinal
        stmt = (
            base.order_by(Position.sort_order, Position.ordinal)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        positions = list(result.scalars().all())

        return positions, total

    async def create(self, position: Position) -> Position:
        """Insert a new position."""
        self.session.add(position)
        await self.session.flush()
        return position

    async def bulk_create(self, positions: list[Position]) -> list[Position]:
        """Insert multiple positions at once."""
        self.session.add_all(positions)
        await self.session.flush()
        return positions

    async def update_fields(self, position_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a position."""
        stmt = update(Position).where(Position.id == position_id).values(**fields)
        await self.session.execute(stmt)

    async def delete(self, position_id: uuid.UUID) -> None:
        """Delete a single position."""
        stmt = delete(Position).where(Position.id == position_id)
        await self.session.execute(stmt)

    async def reorder(self, position_ids: list[uuid.UUID]) -> None:
        """Reorder positions by assigning sort_order based on list index.

        Args:
            position_ids: Ordered list of position UUIDs. Index becomes sort_order.
        """
        for index, pid in enumerate(position_ids):
            stmt = update(Position).where(Position.id == pid).values(sort_order=index)
            await self.session.execute(stmt)

    async def get_max_sort_order(self, boq_id: uuid.UUID) -> int:
        """Get the highest sort_order for positions in a BOQ."""
        stmt = select(func.coalesce(func.max(Position.sort_order), -1)).where(
            Position.boq_id == boq_id
        )
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)
