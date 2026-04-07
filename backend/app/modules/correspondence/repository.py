"""Correspondence data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence


class CorrespondenceRepository:
    """Data access for Correspondence models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, correspondence_id: uuid.UUID) -> Correspondence | None:
        return await self.session.get(Correspondence, correspondence_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        direction: str | None = None,
        correspondence_type: str | None = None,
    ) -> tuple[list[Correspondence], int]:
        base = select(Correspondence).where(Correspondence.project_id == project_id)
        if direction is not None:
            base = base.where(Correspondence.direction == direction)
        if correspondence_type is not None:
            base = base.where(Correspondence.correspondence_type == correspondence_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Correspondence.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def next_reference_number(self, project_id: uuid.UUID) -> str:
        stmt = (
            select(func.count())
            .select_from(Correspondence)
            .where(Correspondence.project_id == project_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"COR-{count + 1:03d}"

    async def create(self, correspondence: Correspondence) -> Correspondence:
        self.session.add(correspondence)
        await self.session.flush()
        return correspondence

    async def update_fields(
        self, correspondence_id: uuid.UUID, **fields: object
    ) -> None:
        stmt = (
            update(Correspondence)
            .where(Correspondence.id == correspondence_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, correspondence_id: uuid.UUID) -> None:
        correspondence = await self.get_by_id(correspondence_id)
        if correspondence is not None:
            await self.session.delete(correspondence)
            await self.session.flush()
