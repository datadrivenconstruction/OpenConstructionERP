# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for legal entities and branches."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.legal_entities.models import Branch, LegalEntity


class LegalEntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, *, include_inactive: bool = False) -> list[LegalEntity]:
        stmt = select(LegalEntity).order_by(LegalEntity.code)
        if not include_inactive:
            stmt = stmt.where(LegalEntity.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, entity_id: uuid.UUID) -> LegalEntity | None:
        return await self.session.get(LegalEntity, entity_id)

    async def get_by_code(self, code: str) -> LegalEntity | None:
        stmt = select(LegalEntity).where(LegalEntity.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_default(self) -> LegalEntity | None:
        stmt = select(LegalEntity).where(LegalEntity.is_default.is_(True)).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def clear_default(self, *, except_id: uuid.UUID | None = None) -> None:
        stmt = update(LegalEntity).where(LegalEntity.is_default.is_(True)).values(is_default=False)
        if except_id is not None:
            stmt = stmt.where(LegalEntity.id != except_id)
        await self.session.execute(stmt.execution_options(synchronize_session="fetch"))

    async def add(self, entity: LegalEntity) -> LegalEntity:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity, attribute_names=["branches"])
        return entity

    async def delete(self, entity: LegalEntity) -> None:
        await self.session.delete(entity)
        await self.session.flush()


class BranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, branch_id: uuid.UUID) -> Branch | None:
        return await self.session.get(Branch, branch_id)

    async def get_by_code(self, entity_id: uuid.UUID, code: str) -> Branch | None:
        stmt = select(Branch).where(Branch.legal_entity_id == entity_id, Branch.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, branch: Branch) -> Branch:
        self.session.add(branch)
        await self.session.flush()
        return branch

    async def delete(self, branch: Branch) -> None:
        await self.session.delete(branch)
        await self.session.flush()
