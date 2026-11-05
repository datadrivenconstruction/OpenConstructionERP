# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger data access layer."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.win_loss.models import BidOutcome


class BidOutcomeRepository:
    """CRUD and filtered listing for ledger entries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entry_id: uuid.UUID) -> BidOutcome | None:
        return await self.session.get(BidOutcome, entry_id)

    async def get_by_tender(self, tender_id: uuid.UUID) -> BidOutcome | None:
        stmt = select(BidOutcome).where(BidOutcome.tender_id == tender_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, entry: BidOutcome) -> BidOutcome:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def update_fields(self, entry_id: uuid.UUID, **fields: Any) -> None:
        if not fields:
            return
        await self.session.execute(update(BidOutcome).where(BidOutcome.id == entry_id).values(**fields))
        await self.session.flush()

    async def delete(self, entry_id: uuid.UUID) -> None:
        await self.session.execute(delete(BidOutcome).where(BidOutcome.id == entry_id))
        await self.session.flush()

    async def list_all(
        self,
        *,
        outcome: str | None = None,
        client: str | None = None,
        limit: int = 10000,
        project_ids: set[uuid.UUID] | None = None,
        offset: int = 0,
    ) -> list[BidOutcome]:
        """List entries; ``project_ids`` (non-admin) hides entries linked to other projects."""
        stmt = self._filtered(select(BidOutcome), outcome, client, project_ids)
        stmt = stmt.order_by(BidOutcome.submitted_on.desc().nullslast(), BidOutcome.created_at.desc(), BidOutcome.id)
        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self, *, outcome: str | None = None, client: str | None = None, project_ids: set[uuid.UUID] | None = None
    ) -> int:
        stmt = self._filtered(select(func.count()).select_from(BidOutcome), outcome, client, project_ids)
        return int((await self.session.execute(stmt)).scalar() or 0)

    @staticmethod
    def _filtered(stmt: Any, outcome: str | None, client: str | None, project_ids: set[uuid.UUID] | None) -> Any:
        if outcome:
            stmt = stmt.where(BidOutcome.outcome == outcome)
        if client:
            stmt = stmt.where(BidOutcome.client_name == client)
        if project_ids is not None:
            stmt = stmt.where(or_(BidOutcome.project_id.is_(None), BidOutcome.project_id.in_(project_ids)))
        return stmt
