# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data-access layer for the review-authority module."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.review_authority.models import Remark, ReviewCycle


class ReviewAuthorityRepository:
    """Data access for :class:`ReviewCycle` and :class:`Remark` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Cycles ─────────────────────────────────────────────────────────

    async def get_cycle(self, cycle_id: uuid.UUID) -> ReviewCycle | None:
        return await self.session.get(ReviewCycle, cycle_id)

    async def list_cycles(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        authority_kind: str | None = None,
    ) -> list[ReviewCycle]:
        stmt = select(ReviewCycle).where(ReviewCycle.project_id == project_id)
        if status is not None:
            stmt = stmt.where(ReviewCycle.status == status)
        if authority_kind is not None:
            stmt = stmt.where(ReviewCycle.authority_kind == authority_kind)
        stmt = stmt.order_by(ReviewCycle.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_cycle(self, cycle: ReviewCycle) -> ReviewCycle:
        self.session.add(cycle)
        await self.session.flush()
        return cycle

    async def delete_cycle(self, cycle_id: uuid.UUID) -> None:
        row = await self.get_cycle(cycle_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    # ── Remarks ────────────────────────────────────────────────────────

    async def get_remark(self, remark_id: uuid.UUID) -> Remark | None:
        return await self.session.get(Remark, remark_id)

    async def list_remarks(self, cycle_id: uuid.UUID) -> list[Remark]:
        stmt = select(Remark).where(Remark.cycle_id == cycle_id).order_by(Remark.ordinal.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_remarks_by_status(self, cycle_id: uuid.UUID, status: str) -> list[Remark]:
        stmt = select(Remark).where(Remark.cycle_id == cycle_id, Remark.status == status).order_by(Remark.ordinal.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def next_ordinal(self, cycle_id: uuid.UUID) -> int:
        """Return the next 1-based ordinal for a new remark on a cycle."""
        stmt = select(func.max(Remark.ordinal)).where(Remark.cycle_id == cycle_id)
        result = await self.session.execute(stmt)
        current = result.scalar_one_or_none()
        return int(current or 0) + 1

    async def create_remark(self, remark: Remark) -> Remark:
        self.session.add(remark)
        await self.session.flush()
        return remark


__all__ = ["ReviewAuthorityRepository"]
