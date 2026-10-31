# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.modules.bid_day.models import BidDayBoard, BidDayEvent, BidDayQuote, BidDayRow, BidDaySnapshot


class BidDayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def board(self, board_id: uuid.UUID) -> BidDayBoard | None:
        return await self.session.get(BidDayBoard, board_id)

    async def board_for_tender(self, tender_id: uuid.UUID) -> BidDayBoard | None:
        stmt = select(BidDayBoard).where(BidDayBoard.tender_id == tender_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def row(self, row_id: uuid.UUID) -> BidDayRow | None:
        return await self.session.get(BidDayRow, row_id)

    async def quote(self, quote_id: uuid.UUID) -> BidDayQuote | None:
        return await self.session.get(BidDayQuote, quote_id)

    async def events(self, board_id: uuid.UUID, limit: int = 60) -> list[BidDayEvent]:
        stmt = (
            select(BidDayEvent)
            .where(BidDayEvent.board_id == board_id)
            .order_by(BidDayEvent.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def snapshots(self, board_id: uuid.UUID) -> list[BidDaySnapshot]:
        stmt = (
            select(BidDaySnapshot).where(BidDaySnapshot.board_id == board_id).order_by(BidDaySnapshot.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def snapshot(self, snapshot_id: uuid.UUID) -> BidDaySnapshot | None:
        return await self.session.get(BidDaySnapshot, snapshot_id)

    async def add(self, *rows: object) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def save(self, row: object, *json_fields: str) -> None:
        for name in json_fields:
            flag_modified(row, name)
        await self.session.flush()

    async def delete(self, row: object) -> None:
        await self.session.delete(row)
        await self.session.flush()
