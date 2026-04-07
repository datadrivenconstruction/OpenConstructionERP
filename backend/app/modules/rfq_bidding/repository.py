"""RFQ Bidding data access layer.

All database queries for RFQ and bid entities live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rfq_bidding.models import RFQ, RFQBid


class RFQRepository:
    """Data access for RFQ model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, rfq_id: uuid.UUID) -> RFQ | None:
        """Get RFQ by ID (with bids via selectin)."""
        return await self.session.get(RFQ, rfq_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RFQ], int]:
        """List RFQs with filters and pagination."""
        base = select(RFQ)

        if project_id is not None:
            base = base.where(RFQ.project_id == project_id)
        if status is not None:
            base = base.where(RFQ.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(RFQ.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, rfq: RFQ) -> RFQ:
        """Insert a new RFQ."""
        self.session.add(rfq)
        await self.session.flush()
        return rfq

    async def update(self, rfq_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an RFQ."""
        stmt = update(RFQ).where(RFQ.id == rfq_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, rfq_id: uuid.UUID) -> None:
        """Delete an RFQ and its bids (cascade)."""
        rfq = await self.get(rfq_id)
        if rfq:
            await self.session.delete(rfq)
            await self.session.flush()

    async def next_rfq_number(self, project_id: uuid.UUID) -> str:
        """Generate the next RFQ number for a project."""
        stmt = (
            select(func.count())
            .select_from(RFQ)
            .where(RFQ.project_id == project_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"RFQ-{count + 1:03d}"


class RFQBidRepository:
    """Data access for RFQBid model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, bid_id: uuid.UUID) -> RFQBid | None:
        """Get bid by ID."""
        return await self.session.get(RFQBid, bid_id)

    async def list(
        self,
        *,
        rfq_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RFQBid], int]:
        """List bids with optional RFQ filter."""
        base = select(RFQBid)
        if rfq_id is not None:
            base = base.where(RFQBid.rfq_id == rfq_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(RFQBid.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, bid: RFQBid) -> RFQBid:
        """Insert a new bid."""
        self.session.add(bid)
        await self.session.flush()
        return bid

    async def update(self, bid_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a bid."""
        stmt = update(RFQBid).where(RFQBid.id == bid_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()
