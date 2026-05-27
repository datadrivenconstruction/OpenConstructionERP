"""Management of Change (MoC) data access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.moc.models import MoCEntry, MoCImpact


class MoCRepository:
    """CRUD for MoCEntry."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_code(self, project_id: uuid.UUID) -> str:
        count = (await self.session.execute(select(func.count()).where(MoCEntry.project_id == project_id))).scalar_one()
        return f"MOC-{count + 1:04d}"

    async def create(self, entry: MoCEntry) -> MoCEntry:
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def get_by_id(self, entry_id: uuid.UUID) -> MoCEntry | None:
        return await self.session.get(MoCEntry, entry_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[MoCEntry], int]:
        base = select(MoCEntry).where(MoCEntry.project_id == project_id)
        if status is not None:
            base = base.where(MoCEntry.status == status)
        count = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(MoCEntry.created_at.desc()).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, count

    async def update_fields(self, entry_id: uuid.UUID, **fields: object) -> None:
        entry = await self.get_by_id(entry_id)
        if entry is None:
            return
        for k, v in fields.items():
            setattr(entry, k, v)
        await self.session.flush()

    async def delete(self, entry_id: uuid.UUID) -> None:
        entry = await self.get_by_id(entry_id)
        if entry is not None:
            await self.session.delete(entry)
            await self.session.flush()


class MoCImpactRepository:
    """CRUD for MoCImpact."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, impact: MoCImpact) -> MoCImpact:
        self.session.add(impact)
        await self.session.flush()
        await self.session.refresh(impact)
        return impact

    async def get_by_id(self, impact_id: uuid.UUID) -> MoCImpact | None:
        return await self.session.get(MoCImpact, impact_id)

    async def list_for_entry(self, entry_id: uuid.UUID) -> list[MoCImpact]:
        result = await self.session.execute(select(MoCImpact).where(MoCImpact.moc_entry_id == entry_id))
        return list(result.scalars().all())

    async def update_fields(self, impact_id: uuid.UUID, **fields: object) -> None:
        impact = await self.get_by_id(impact_id)
        if impact is None:
            return
        for k, v in fields.items():
            setattr(impact, k, v)
        await self.session.flush()

    async def delete(self, impact_id: uuid.UUID) -> None:
        impact = await self.get_by_id(impact_id)
        if impact is not None:
            await self.session.delete(impact)
            await self.session.flush()
