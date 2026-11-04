# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.modules.bid_no_bid.models import BidNoBidEvent, BidNoBidScorecard


class BidNoBidRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def card(self, card_id: uuid.UUID) -> BidNoBidScorecard | None:
        return await self.session.get(BidNoBidScorecard, card_id)

    async def card_for_tender(self, tender_id: uuid.UUID) -> BidNoBidScorecard | None:
        stmt = select(BidNoBidScorecard).where(BidNoBidScorecard.tender_id == tender_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def cards(self, project_id: uuid.UUID | None, limit: int = 500) -> list[BidNoBidScorecard]:
        stmt = select(BidNoBidScorecard).order_by(BidNoBidScorecard.created_at.desc()).limit(limit)
        if project_id is not None:
            stmt = stmt.where(BidNoBidScorecard.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def events(self, card_id: uuid.UUID, limit: int = 100) -> list[BidNoBidEvent]:
        stmt = (
            select(BidNoBidEvent)
            .where(BidNoBidEvent.scorecard_id == card_id)
            .order_by(BidNoBidEvent.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, *rows: object) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def save(self, row: object, *json_fields: str) -> None:
        for name in json_fields:
            flag_modified(row, name)
        await self.session.flush()
