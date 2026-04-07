"""Submittals data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.submittals.models import Submittal


class SubmittalRepository:
    """Data access for Submittal models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, submittal_id: uuid.UUID) -> Submittal | None:
        return await self.session.get(Submittal, submittal_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        submittal_type: str | None = None,
    ) -> tuple[list[Submittal], int]:
        base = select(Submittal).where(Submittal.project_id == project_id)
        if status is not None:
            base = base.where(Submittal.status == status)
        if submittal_type is not None:
            base = base.where(Submittal.submittal_type == submittal_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Submittal.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def next_submittal_number(self, project_id: uuid.UUID) -> str:
        stmt = (
            select(func.count())
            .select_from(Submittal)
            .where(Submittal.project_id == project_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"SUB-{count + 1:03d}"

    async def create(self, submittal: Submittal) -> Submittal:
        self.session.add(submittal)
        await self.session.flush()
        return submittal

    async def update_fields(self, submittal_id: uuid.UUID, **fields: object) -> None:
        stmt = update(Submittal).where(Submittal.id == submittal_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, submittal_id: uuid.UUID) -> None:
        submittal = await self.get_by_id(submittal_id)
        if submittal is not None:
            await self.session.delete(submittal)
            await self.session.flush()
