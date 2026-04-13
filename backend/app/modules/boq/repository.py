"""BOQ data access layer.

All database queries for BOQs, positions, markups, and activity logs live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.modules.boq.models import BOQ, BOQActivityLog, BOQMarkup, Position


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
        """List BOQs for a project with pagination. Returns (boqs, total_count).

        Positions and markups are NOT eagerly loaded here — use
        ``grand_totals_for_boqs`` to compute totals via a single aggregate query.
        """
        base = select(BOQ).where(BOQ.project_id == project_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch — skip eager loading of positions/markups for list queries
        stmt = (
            base.options(noload(BOQ.positions), noload(BOQ.markups))
            .order_by(BOQ.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        boqs = list(result.scalars().all())

        return boqs, total

    async def grand_totals_for_boqs(
        self,
        boq_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]:
        """Compute grand total (direct cost + markups) for each BOQ by ID.

        First aggregates position totals per BOQ, then applies active markups
        (percentage or fixed) in sort_order to arrive at the final grand total.
        Returns a mapping of boq_id -> grand_total.
        """
        if not boq_ids:
            return {}

        from decimal import Decimal

        from sqlalchemy import Float, cast

        # Step 1: sum direct cost (position totals) per BOQ
        pos_stmt = (
            select(
                Position.boq_id,
                func.sum(cast(Position.total, Float)).label("direct_cost"),
            )
            .where(Position.boq_id.in_(boq_ids))
            .group_by(Position.boq_id)
        )
        pos_result = await self.session.execute(pos_stmt)
        direct_costs: dict[uuid.UUID, float] = {row.boq_id: float(row.direct_cost or 0) for row in pos_result}

        # Step 2: fetch active markups for all requested BOQs
        markup_stmt = (
            select(BOQMarkup)
            .where(BOQMarkup.boq_id.in_(boq_ids), BOQMarkup.is_active.is_(True))
            .order_by(BOQMarkup.sort_order)
        )
        markup_result = await self.session.execute(markup_stmt)
        markups_by_boq: dict[uuid.UUID, list[BOQMarkup]] = {}
        for markup in markup_result.scalars().all():
            markups_by_boq.setdefault(markup.boq_id, []).append(markup)

        # Step 3: apply markups to compute grand total per BOQ
        totals: dict[uuid.UUID, float] = {}
        for boq_id in boq_ids:
            dc = Decimal(str(direct_costs.get(boq_id, 0)))
            running = dc
            for m in markups_by_boq.get(boq_id, []):
                if m.markup_type == "percentage":
                    pct = Decimal(m.percentage or "0")
                    base = running if m.apply_to == "cumulative" else dc
                    running += base * pct / Decimal("100")
                elif m.markup_type == "fixed":
                    running += Decimal(m.fixed_amount or "0")
            totals[boq_id] = round(float(running), 2)

        return totals

    async def create(self, boq: BOQ) -> BOQ:
        """Insert a new BOQ."""
        self.session.add(boq)
        await self.session.flush()
        return boq

    async def update_fields(self, boq_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a BOQ."""
        stmt = update(BOQ).where(BOQ.id == boq_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

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

    async def list_children(self, parent_id: uuid.UUID) -> list[Position]:
        """List direct children of a position (one level only)."""
        stmt = select(Position).where(Position.parent_id == parent_id).order_by(Position.sort_order)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
        stmt = base.order_by(Position.sort_order, Position.ordinal).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        positions = list(result.scalars().all())

        return positions, total

    async def create(self, position: Position) -> Position:
        """Insert a new position."""
        self.session.add(position)
        await self.session.flush()
        await self.session.refresh(position)
        return position

    async def bulk_create(self, positions: list[Position]) -> list[Position]:
        """Insert multiple positions at once."""
        self.session.add_all(positions)
        await self.session.flush()
        for pos in positions:
            await self.session.refresh(pos)
        return positions

    async def update_fields(self, position_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a position."""
        stmt = update(Position).where(Position.id == position_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

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
        stmt = select(func.coalesce(func.max(Position.sort_order), -1)).where(Position.boq_id == boq_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)

    async def ordinal_exists(self, boq_id: uuid.UUID, ordinal: str, exclude_id: uuid.UUID | None = None) -> bool:
        """Check if a position with the given ordinal already exists in the BOQ.

        Args:
            boq_id: The BOQ to check in.
            ordinal: The ordinal string to check for duplicates.
            exclude_id: Optional position ID to exclude (for update checks).

        Returns:
            True if a position with this ordinal already exists.
        """
        stmt = select(func.count()).where(Position.boq_id == boq_id, Position.ordinal == ordinal)
        if exclude_id is not None:
            stmt = stmt.where(Position.id != exclude_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result) > 0


class MarkupRepository:
    """Data access for BOQMarkup model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, markup_id: uuid.UUID) -> BOQMarkup | None:
        """Get a markup by ID."""
        return await self.session.get(BOQMarkup, markup_id)

    async def list_for_boq(self, boq_id: uuid.UUID) -> list[BOQMarkup]:
        """List all markups for a BOQ ordered by sort_order."""
        stmt = select(BOQMarkup).where(BOQMarkup.boq_id == boq_id).order_by(BOQMarkup.sort_order, BOQMarkup.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, markup: BOQMarkup) -> BOQMarkup:
        """Insert a new markup."""
        self.session.add(markup)
        await self.session.flush()
        await self.session.refresh(markup)
        return markup

    async def bulk_create(self, markups: list[BOQMarkup]) -> list[BOQMarkup]:
        """Insert multiple markups at once."""
        self.session.add_all(markups)
        await self.session.flush()
        for m in markups:
            await self.session.refresh(m)
        return markups

    async def update_fields(self, markup_id: uuid.UUID, **fields: object) -> BOQMarkup | None:
        """Update specific fields on a markup and return refreshed object."""
        stmt = update(BOQMarkup).where(BOQMarkup.id == markup_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        markup = await self.session.get(BOQMarkup, markup_id)
        if markup is not None:
            await self.session.refresh(markup)
        return markup

    async def delete(self, markup_id: uuid.UUID) -> None:
        """Delete a single markup."""
        stmt = delete(BOQMarkup).where(BOQMarkup.id == markup_id)
        await self.session.execute(stmt)

    async def delete_all_for_boq(self, boq_id: uuid.UUID) -> None:
        """Delete all markups for a BOQ (used before applying defaults)."""
        stmt = delete(BOQMarkup).where(BOQMarkup.boq_id == boq_id)
        await self.session.execute(stmt)

    async def get_max_sort_order(self, boq_id: uuid.UUID) -> int:
        """Get the highest sort_order for markups in a BOQ."""
        stmt = select(func.coalesce(func.max(BOQMarkup.sort_order), -1)).where(BOQMarkup.boq_id == boq_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)


class ActivityLogRepository:
    """Data access for BOQActivityLog model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entry: BOQActivityLog) -> BOQActivityLog:
        """Insert a new activity log entry."""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_for_boq(
        self,
        boq_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQActivityLog], int]:
        """List activity log entries for a BOQ, newest first.

        Returns (entries, total_count).
        """
        base = select(BOQActivityLog).where(BOQActivityLog.boq_id == boq_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BOQActivityLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        entries = list(result.scalars().all())

        return entries, total

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQActivityLog], int]:
        """List activity log entries for a project, newest first.

        Returns (entries, total_count).
        """
        base = select(BOQActivityLog).where(BOQActivityLog.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BOQActivityLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        entries = list(result.scalars().all())

        return entries, total
