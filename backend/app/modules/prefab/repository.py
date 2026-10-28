# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Off-site / Prefab / DfMA data access layer.

All database queries for prefab units and their production events live here.
No business logic - pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.prefab.models import PrefabUnit, ProductionEvent


class PrefabUnitRepository:
    """Data access for PrefabUnit models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, unit_id: uuid.UUID) -> PrefabUnit | None:
        """Get a unit by ID."""
        return await self.session.get(PrefabUnit, unit_id)

    async def get_by_ref_and_project(
        self,
        project_id: uuid.UUID,
        ref: str,
    ) -> PrefabUnit | None:
        """Get a unit by its reference within a project (uniqueness check)."""
        stmt = select(PrefabUnit).where(
            PrefabUnit.project_id == project_id,
            PrefabUnit.ref == ref,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        unit_type: str | None = None,
    ) -> tuple[list[PrefabUnit], int]:
        """List units for a project with pagination and optional filters."""
        base = select(PrefabUnit).where(PrefabUnit.project_id == project_id)
        if status is not None:
            base = base.where(PrefabUnit.status == status)
        if unit_type is not None:
            base = base.where(PrefabUnit.unit_type == unit_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PrefabUnit.ref.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    async def create(self, unit: PrefabUnit) -> PrefabUnit:
        """Insert a new unit."""
        self.session.add(unit)
        await self.session.flush()
        return unit

    async def update_fields(self, unit_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a unit."""
        stmt = update(PrefabUnit).where(PrefabUnit.id == unit_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(PrefabUnit, unit_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, unit_id: uuid.UUID) -> None:
        """Delete a unit (its production events cascade via the FK)."""
        unit = await self.session.get(PrefabUnit, unit_id)
        if unit is not None:
            await self.session.delete(unit)
            await self.session.flush()

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        """Compute aggregate statistics for a project's prefab units.

        Returns a dict with keys: ``total``, ``by_status``, ``by_type``.
        """
        total_stmt = select(func.count()).select_from(PrefabUnit).where(PrefabUnit.project_id == project_id)
        total = (await self.session.execute(total_stmt)).scalar_one()

        status_stmt = (
            select(PrefabUnit.status, func.count())
            .where(PrefabUnit.project_id == project_id)
            .group_by(PrefabUnit.status)
        )
        by_status = {row[0]: row[1] for row in (await self.session.execute(status_stmt)).all()}

        type_stmt = (
            select(PrefabUnit.unit_type, func.count())
            .where(PrefabUnit.project_id == project_id)
            .group_by(PrefabUnit.unit_type)
        )
        by_type = {row[0]: row[1] for row in (await self.session.execute(type_stmt)).all()}

        return {"total": total, "by_status": by_status, "by_type": by_type}


class ProductionEventRepository:
    """Data access for ProductionEvent models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_unit(self, unit_id: uuid.UUID) -> list[ProductionEvent]:
        """Return the production-event audit log for a unit, newest first."""
        stmt = select(ProductionEvent).where(ProductionEvent.unit_id == unit_id).order_by(ProductionEvent.at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, event: ProductionEvent) -> ProductionEvent:
        """Insert a new production event."""
        self.session.add(event)
        await self.session.flush()
        return event
