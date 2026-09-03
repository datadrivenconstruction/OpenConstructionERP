# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFQ Bidding data access layer.

All database queries for RFQ and bid entities live here.
No business logic - pure data access.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.orm_write import apply_update
from app.modules.rfq_bidding.models import (
    RFQ,
    RFQAward,
    RFQBid,
    RFQBidAdjustment,
    RFQLine,
)


class RFQRepository:
    """Data access for RFQ model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, rfq_id: uuid.UUID) -> RFQ | None:
        """Get RFQ by ID, with its bids loaded.

        Issued as a query rather than ``session.get``, and with
        ``populate_existing`` so the ``selectin`` loader on ``RFQ.bids`` runs
        even when the session already holds the RFQ. Both halves are needed.
        ``session.get`` answers from the identity map without querying at all,
        and a plain query leaves an already-loaded collection alone: an RFQ
        created in this session has an empty ``bids`` list from before any bid
        existed, and it would stay empty for the rest of the request.

        This used to be hidden by repository writes calling ``expire_all()``,
        which invalidated the instance and forced the next read to re-query.
        Those writes now reconcile only the row they touched, so a fresh view
        has to be asked for rather than fall out of a side effect.
        ``award_bid`` walks ``rfq.bids`` to refuse a second award, and read it
        as empty, so the guard passed and both bids could be awarded.
        """
        result = await self.session.execute(
            select(RFQ).where(RFQ.id == rfq_id).execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

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
        await apply_update(self.session, RFQ, rfq_id, **fields)

    async def delete(self, rfq_id: uuid.UUID) -> None:
        """Delete an RFQ and its bids (cascade)."""
        rfq = await self.get(rfq_id)
        if rfq:
            await self.session.delete(rfq)
            await self.session.flush()

    async def next_rfq_number(self, project_id: uuid.UUID) -> str:
        """Generate the next RFQ number using MAX to avoid collisions after deletions."""
        stmt = select(func.max(RFQ.rfq_number)).where(RFQ.project_id == project_id)
        max_number = (await self.session.execute(stmt)).scalar_one()
        if max_number is None:
            return "RFQ-001"
        try:
            numeric = int(max_number.split("-", 1)[1])
        except (IndexError, ValueError):
            numeric = 0
        return f"RFQ-{numeric + 1:03d}"


class RFQLineRepository:
    """Data access for the scope lines of an RFQ."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, line_id: uuid.UUID) -> RFQLine | None:
        """Get one scope line by ID."""
        return await self.session.get(RFQLine, line_id)

    async def list_for_rfq(self, rfq_id: uuid.UUID) -> list[RFQLine]:
        """Every scope line of one RFQ, in line order."""
        result = await self.session.execute(select(RFQLine).where(RFQLine.rfq_id == rfq_id).order_by(RFQLine.line_no))
        return list(result.scalars().all())

    async def create(self, line: RFQLine) -> RFQLine:
        """Insert a new scope line."""
        self.session.add(line)
        await self.session.flush()
        return line

    async def update(self, line_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a scope line."""
        await apply_update(self.session, RFQLine, line_id, **fields)

    async def delete(self, line: RFQLine) -> None:
        """Delete a scope line and any quoted lines that referenced it."""
        await self.session.delete(line)
        await self.session.flush()

    async def next_line_no(self, rfq_id: uuid.UUID) -> int:
        """The next free line number, taken from the current maximum.

        Counting rows would reuse a number after a deletion and collide with
        the ``(rfq_id, line_no)`` unique constraint.
        """
        stmt = select(func.max(RFQLine.line_no)).where(RFQLine.rfq_id == rfq_id)
        current = (await self.session.execute(stmt)).scalar_one()
        return int(current or 0) + 1


class RFQBidRepository:
    """Data access for RFQBid model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, bid_id: uuid.UUID) -> RFQBid | None:
        """Get bid by ID, with its lines and adjustments loaded.

        A real query with ``populate_existing`` rather than ``session.get``,
        for the same reason as :meth:`RFQRepository.get`: ``session.get``
        answers from the identity map, so a bid just created in this session
        comes back with its never-touched ``lines``/``adjustments``
        collections unloaded - and serialising it then trips MissingGreenlet
        in pydantic's sync attribute access.
        """
        stmt = select(RFQBid).where(RFQBid.id == bid_id).execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

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
        await apply_update(self.session, RFQBid, bid_id, **fields)

    async def add_adjustment(self, adjustment: RFQBidAdjustment) -> RFQBidAdjustment:
        """Insert one inclusion or exclusion against an existing quote."""
        self.session.add(adjustment)
        await self.session.flush()
        return adjustment


class RFQAwardRepository:
    """Data access for the award decision record.

    One row per RFQ, written when a quote is awarded and never rewritten: the
    ranked table it carries is the state of the comparison at that moment, and
    recomputing it later answers a different question.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_rfq(self, rfq_id: uuid.UUID) -> RFQAward | None:
        """The award record of one RFQ, or ``None`` if it has not been awarded."""
        result = await self.session.execute(select(RFQAward).where(RFQAward.rfq_id == rfq_id))
        return result.scalar_one_or_none()

    async def create(self, award: RFQAward) -> RFQAward:
        """Insert the award record."""
        self.session.add(award)
        await self.session.flush()
        return award
