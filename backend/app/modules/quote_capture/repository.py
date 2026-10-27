# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.modules.quote_capture.models import CapturedQuote


class QuoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, quote_id: uuid.UUID) -> CapturedQuote | None:
        return await self.session.get(CapturedQuote, quote_id)

    async def list(
        self, project_id: uuid.UUID, *, package_id: uuid.UUID | None = None, include_rejected: bool = True
    ) -> list[CapturedQuote]:
        stmt = select(CapturedQuote).where(CapturedQuote.project_id == project_id)
        if package_id is not None:
            stmt = stmt.where(CapturedQuote.package_id == package_id)
        if not include_rejected:
            stmt = stmt.where(CapturedQuote.status != "rejected")
        stmt = stmt.order_by(CapturedQuote.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_package(self, package_id: uuid.UUID) -> list[CapturedQuote]:
        stmt = (
            select(CapturedQuote)
            .where(CapturedQuote.package_id == package_id, CapturedQuote.status != "rejected")
            .order_by(CapturedQuote.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, row: CapturedQuote) -> CapturedQuote:
        self.session.add(row)
        await self.session.flush()
        return row

    async def save(self, row: CapturedQuote, *json_fields: str) -> CapturedQuote:
        for name in json_fields:
            flag_modified(row, name)
        await self.session.flush()
        return row

    async def delete(self, row: CapturedQuote) -> None:
        await self.session.delete(row)
        await self.session.flush()
