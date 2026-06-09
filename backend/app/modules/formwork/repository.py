"""Formwork data access layer."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.formwork.models import (
    FormworkAssignment,
    FormworkScheduleLine,
    FormworkSystem,
)


class _CRUDBase:
    """Shared CRUD primitives for formwork repositories."""

    model: type
    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, item_id)

    async def create(self, item: Any) -> Any:
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(self.model).where(self.model.id == item_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, item_id: uuid.UUID) -> None:
        obj = await self.get_by_id(item_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


class FormworkSystemRepository(_CRUDBase):
    model = FormworkSystem

    async def list_filtered(
        self,
        *,
        tenant_id: uuid.UUID | None = None,
        system_type: str | None = None,
        material: str | None = None,
        supplier: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[FormworkSystem]:
        stmt = select(FormworkSystem)
        # Tenant scoping: a None tenant_id query matches global rows
        # (tenant_id IS NULL); a UUID matches that tenant only.
        if tenant_id is not None:
            stmt = stmt.where((FormworkSystem.tenant_id == tenant_id) | (FormworkSystem.tenant_id.is_(None)))
        if system_type:
            stmt = stmt.where(FormworkSystem.system_type == system_type)
        if material:
            stmt = stmt.where(FormworkSystem.material == material)
        if supplier:
            stmt = stmt.where(FormworkSystem.supplier == supplier)
        stmt = stmt.order_by(FormworkSystem.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_names_for_tenant(
        self,
        tenant_id: uuid.UUID | None,
    ) -> set[str]:
        """Names visible to ``tenant_id``, used by the seed endpoint to skip
        already-installed defaults.

        Visibility must match :meth:`list_filtered`: a tenant sees its own
        rows **and** global (``tenant_id IS NULL``) rows. If we only matched
        the exact tenant here, seeding for a tenant would re-insert a
        tenant-scoped copy of every default that already exists globally,
        and the catalogue list would then show each starter system twice.
        """
        stmt = select(FormworkSystem.name)
        if tenant_id is not None:
            stmt = stmt.where((FormworkSystem.tenant_id == tenant_id) | (FormworkSystem.tenant_id.is_(None)))
        else:
            stmt = stmt.where(FormworkSystem.tenant_id.is_(None))
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}


class FormworkAssignmentRepository(_CRUDBase):
    model = FormworkAssignment

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[FormworkAssignment]:
        stmt = (
            select(FormworkAssignment)
            .where(FormworkAssignment.project_id == project_id)
            .order_by(FormworkAssignment.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class FormworkScheduleLineRepository(_CRUDBase):
    model = FormworkScheduleLine

    async def list_for_assignment(
        self,
        assignment_id: uuid.UUID,
    ) -> list[FormworkScheduleLine]:
        stmt = (
            select(FormworkScheduleLine)
            .where(FormworkScheduleLine.assignment_id == assignment_id)
            .order_by(FormworkScheduleLine.pour_no)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
