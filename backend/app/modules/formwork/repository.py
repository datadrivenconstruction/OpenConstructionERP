# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Formwork data access layer."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

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
        instance = self.session.identity_map.get(identity_key(self.model, item_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

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

    async def count_visible(self, tenant_id: uuid.UUID | None) -> int:
        """Number of catalogue rows visible to ``tenant_id``.

        The seed endpoint reports this AFTER inserting rather than adding its
        insert count to the number of distinct names it saw first: a name that
        exists both globally and tenant-scoped collapses in a name set, so the
        derived figure under-reported the catalogue by every such duplicate.
        """
        stmt = select(func.count(FormworkSystem.id))
        if tenant_id is not None:
            stmt = stmt.where(
                (FormworkSystem.tenant_id == tenant_id) | (FormworkSystem.tenant_id.is_(None)),
            )
        else:
            stmt = stmt.where(FormworkSystem.tenant_id.is_(None))
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)


class FormworkAssignmentRepository(_CRUDBase):
    model = FormworkAssignment

    async def get_with_system(
        self,
        assignment_id: uuid.UUID,
    ) -> FormworkAssignment | None:
        """One assignment with its catalogue system eagerly loaded.

        ``FormworkAssignment.system`` is ``raise_on_sql``, so anything that
        reads the rate build-up has to come through here (or another eager
        path) rather than walking the relationship off a bare ``session.get``.
        """
        stmt = (
            select(FormworkAssignment)
            .where(FormworkAssignment.id == assignment_id)
            .options(selectinload(FormworkAssignment.system))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        with_system: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[FormworkAssignment]:
        """Assignments on one project, newest first.

        ``with_system`` eagerly loads the catalogue row for each assignment so
        the detail response can carry the system name, material and currency
        without one query per row.
        """
        stmt = (
            select(FormworkAssignment)
            .where(FormworkAssignment.project_id == project_id)
            .order_by(FormworkAssignment.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if with_system:
            stmt = stmt.options(selectinload(FormworkAssignment.system))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_for_project(
        self,
        project_id: uuid.UUID,
    ) -> list[FormworkAssignment]:
        """Every assignment on a project with its system, for rollup and validation.

        Unpaged on purpose: the project summary and the project-scope validation
        pass are both defined over the whole set, and a partial page would make
        the totals silently wrong. Formwork assignments are per-element, tens
        to low hundreds per project, not a table scan.
        """
        stmt = (
            select(FormworkAssignment)
            .where(FormworkAssignment.project_id == project_id)
            .options(selectinload(FormworkAssignment.system))
            .order_by(FormworkAssignment.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_system(
        self,
        system_id: uuid.UUID,
    ) -> list[FormworkAssignment]:
        """Every assignment priced off one catalogue system.

        Drives re-pricing after a catalogue rate change. Queried directly
        rather than through ``FormworkSystem.assignments`` (``raise_on_sql``)
        so the access is explicit at the call site.
        """
        stmt = select(FormworkAssignment).where(
            FormworkAssignment.formwork_system_id == system_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def usage_for_system(self, system_id: uuid.UUID) -> dict[str, Any]:
        """Aggregate dependency of assignments on one catalogue system.

        Aggregated in SQL rather than by loading rows, because this is read on
        every catalogue screen and the answer is four scalars.
        """
        stmt = select(
            func.count(FormworkAssignment.id),
            func.count(func.distinct(FormworkAssignment.project_id)),
            func.coalesce(func.sum(FormworkAssignment.area_m2), 0),
            func.coalesce(func.sum(FormworkAssignment.computed_total), 0),
        ).where(FormworkAssignment.formwork_system_id == system_id)
        result = await self.session.execute(stmt)
        row = result.one()
        return {
            "assignment_count": int(row[0] or 0),
            "project_count": int(row[1] or 0),
            "total_area_m2": row[2] or 0,
            "total_cost": row[3] or 0,
        }

    async def count_for_boq_position(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
    ) -> int:
        """How many assignments on a project point at one BOQ position.

        More than one means the same bill line is being charged formwork twice.
        """
        stmt = select(func.count(FormworkAssignment.id)).where(
            FormworkAssignment.project_id == project_id,
            FormworkAssignment.boq_position_id == boq_position_id,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)


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

    async def list_for_assignments(
        self,
        assignment_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[FormworkScheduleLine]]:
        """Pour lines for many assignments at once, grouped by parent id.

        The project-wide validation pass needs the cycle of every assignment;
        without this it would be one query per assignment.
        """
        if not assignment_ids:
            return {}
        stmt = (
            select(FormworkScheduleLine)
            .where(FormworkScheduleLine.assignment_id.in_(assignment_ids))
            .order_by(FormworkScheduleLine.assignment_id, FormworkScheduleLine.pour_no)
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[FormworkScheduleLine]] = {aid: [] for aid in assignment_ids}
        for line in result.scalars().all():
            grouped.setdefault(line.assignment_id, []).append(line)
        return grouped
