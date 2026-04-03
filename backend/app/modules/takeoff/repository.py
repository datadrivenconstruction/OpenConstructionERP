"""Takeoff data access layer."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.takeoff.models import TakeoffDocument


class TakeoffRepository:
    """Data access for TakeoffDocument model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, doc_id: uuid.UUID) -> TakeoffDocument | None:
        return await self.session.get(TakeoffDocument, doc_id)

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[TakeoffDocument]:
        stmt = select(TakeoffDocument).where(TakeoffDocument.owner_id == owner_id)
        if project_id:
            stmt = stmt.where(TakeoffDocument.project_id == project_id)
        stmt = stmt.order_by(TakeoffDocument.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, doc: TakeoffDocument) -> TakeoffDocument:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_fields(self, doc_id: uuid.UUID, **fields: object) -> None:
        stmt = update(TakeoffDocument).where(TakeoffDocument.id == doc_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, doc_id: uuid.UUID) -> None:
        doc = await self.get_by_id(doc_id)
        if doc is not None:
            await self.session.delete(doc)
            await self.session.flush()
