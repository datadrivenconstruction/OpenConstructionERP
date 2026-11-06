"""Customer offer data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.offers.models import Offer, OfferSettings, OfferTextBlock


class OfferRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, offer_id: uuid.UUID) -> Offer | None:
        return await self.session.get(Offer, offer_id)

    async def list_for_boq(self, boq_id: uuid.UUID) -> list[Offer]:
        stmt = select(Offer).where(Offer.boq_id == boq_id).order_by(Offer.created_at.desc()).limit(200)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_page(
        self, project_id: uuid.UUID, boq_id: uuid.UUID | None, *, offset: int, limit: int
    ) -> tuple[list[Offer], int]:
        cond = [Offer.project_id == project_id]
        if boq_id is not None:
            cond.append(Offer.boq_id == boq_id)
        total = (await self.session.execute(select(func.count()).select_from(Offer).where(*cond))).scalar_one()
        stmt = select(Offer).where(*cond).order_by(Offer.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), int(total)

    async def revisions(self, group_id: uuid.UUID) -> list[Offer]:
        stmt = select(Offer).where(Offer.group_id == group_id).order_by(Offer.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def numbers(self) -> list[str]:
        return list((await self.session.execute(select(Offer.number).distinct())).scalars().all())

    async def number_taken(self, number: str, group_id: uuid.UUID | None) -> bool:
        stmt = select(Offer.group_id).where(Offer.number == number).distinct()
        groups = set((await self.session.execute(stmt)).scalars().all())
        return bool(groups - ({group_id} if group_id else set()))

    async def add(self, offer: Offer) -> Offer:
        self.session.add(offer)
        await self.session.flush()
        return offer

    # -- text library -----------------------------------------------------------------------

    async def text_blocks(
        self, *, project_id: uuid.UUID | None = None, kind: str | None = None, scope: str | None = None
    ) -> list[OfferTextBlock]:
        stmt = select(OfferTextBlock)
        if scope:
            stmt = stmt.where(OfferTextBlock.scope == scope)
        if project_id is not None:
            stmt = stmt.where(OfferTextBlock.project_id == project_id)
        if kind:
            stmt = stmt.where(OfferTextBlock.kind == kind)
        stmt = stmt.order_by(OfferTextBlock.kind, OfferTextBlock.language, OfferTextBlock.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def text_block(self, block_id: uuid.UUID) -> OfferTextBlock | None:
        return await self.session.get(OfferTextBlock, block_id)

    async def add_text_block(self, block: OfferTextBlock) -> OfferTextBlock:
        self.session.add(block)
        await self.session.flush()
        return block

    async def delete_text_block(self, block: OfferTextBlock) -> None:
        await self.session.delete(block)
        await self.session.flush()

    # -- settings ---------------------------------------------------------------------------

    async def settings(self) -> OfferSettings:
        row = (
            await self.session.execute(select(OfferSettings).where(OfferSettings.key == "default"))
        ).scalar_one_or_none()
        if row is None:
            row = OfferSettings(key="default")
            self.session.add(row)
            await self.session.flush()
        return row
