"""‌⁠‍Carbon & Sustainability data-access layer.

One repository per entity. Methods follow the convention used elsewhere
in the codebase: ``get_by_id``, ``list_for_*``, ``create``,
``update_fields``, ``delete``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.carbon.models import (
    CarbonInventory,
    CarbonTarget,
    EmbodiedCarbonEntry,
    EPDRecord,
    MaterialCarbonFactor,
    Scope1Entry,
    Scope2Entry,
    Scope3Entry,
    SustainabilityReport,
)


class _BaseRepo:
    """‌⁠‍Shared CRUD primitives."""

    model: type

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, obj_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return await self.session.get(self.model, obj_id)

    async def create(self, obj):  # type: ignore[no-untyped-def]
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_fields(self, obj_id: uuid.UUID, **fields: object) -> None:
        stmt = update(self.model).where(self.model.id == obj_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, obj_id: uuid.UUID) -> None:
        obj = await self.get_by_id(obj_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


# ── EPD records ───────────────────────────────────────────────────────────


class EPDRecordRepository(_BaseRepo):
    """‌⁠‍Data access for EPDRecord."""

    model = EPDRecord

    async def list_filtered(
        self,
        *,
        material_class: str | None = None,
        region: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[EPDRecord], int]:
        base = select(EPDRecord)
        if material_class is not None:
            base = base.where(EPDRecord.material_class == material_class)
        if region is not None:
            base = base.where(EPDRecord.region == region)
        count = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery()),
            )
        ).scalar_one()
        stmt = base.order_by(EPDRecord.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(count)

    async def find_epd_by_material_class(
        self,
        material_class: str,
        region: str | None = None,
    ) -> EPDRecord | None:
        stmt = select(EPDRecord).where(EPDRecord.material_class == material_class)
        if region is not None:
            stmt = stmt.where(EPDRecord.region == region)
        result = await self.session.execute(stmt.limit(1))
        return result.scalars().first()

    async def get_by_epd_id(self, epd_id: str) -> EPDRecord | None:
        """Look up a record by its tenant-unique external EPD identifier."""
        result = await self.session.execute(
            select(EPDRecord).where(EPDRecord.epd_id == epd_id).limit(1),
        )
        return result.scalars().first()


# ── Material factors ──────────────────────────────────────────────────────


class MaterialFactorRepository(_BaseRepo):
    """Data access for MaterialCarbonFactor."""

    model = MaterialCarbonFactor

    async def list_filtered(
        self,
        *,
        cost_item_id: uuid.UUID | None = None,
        region: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[MaterialCarbonFactor], int]:
        base = select(MaterialCarbonFactor)
        if cost_item_id is not None:
            base = base.where(MaterialCarbonFactor.cost_item_id == cost_item_id)
        if region is not None:
            base = base.where(MaterialCarbonFactor.region == region)
        count = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery()),
            )
        ).scalar_one()
        stmt = base.order_by(MaterialCarbonFactor.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(count)


# ── Inventory ─────────────────────────────────────────────────────────────


class InventoryRepository(_BaseRepo):
    """Data access for CarbonInventory."""

    model = CarbonInventory

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CarbonInventory], int]:
        base = select(CarbonInventory).where(CarbonInventory.project_id == project_id)
        count = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery()),
            )
        ).scalar_one()
        stmt = base.order_by(CarbonInventory.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(count)


# ── Embodied entries ──────────────────────────────────────────────────────


class EmbodiedEntryRepository(_BaseRepo):
    """Data access for EmbodiedCarbonEntry."""

    model = EmbodiedCarbonEntry

    async def list_for_inventory(
        self,
        inventory_id: uuid.UUID,
    ) -> list[EmbodiedCarbonEntry]:
        stmt = select(EmbodiedCarbonEntry).where(
            EmbodiedCarbonEntry.inventory_id == inventory_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_inventory_paged(
        self,
        inventory_id: uuid.UUID,
        *,
        stage: str | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[EmbodiedCarbonEntry], int]:
        base = select(EmbodiedCarbonEntry).where(
            EmbodiedCarbonEntry.inventory_id == inventory_id,
        )
        if stage is not None:
            base = base.where(EmbodiedCarbonEntry.stage == stage)
        count = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery()),
            )
        ).scalar_one()
        stmt = base.order_by(EmbodiedCarbonEntry.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(count)

    async def entries_by_stage(
        self,
        inventory_id: uuid.UUID,
        stage: str,
    ) -> list[EmbodiedCarbonEntry]:
        stmt = select(EmbodiedCarbonEntry).where(
            (EmbodiedCarbonEntry.inventory_id == inventory_id) & (EmbodiedCarbonEntry.stage == stage),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Scope 1/2/3 ───────────────────────────────────────────────────────────


class _ScopeRepoMixin:
    """Mixin so each scope-N repo shares the ``list_for_inventory`` shape."""

    model: type
    session: AsyncSession

    async def list_for_inventory(self, inventory_id: uuid.UUID):  # type: ignore[no-untyped-def]
        stmt = select(self.model).where(self.model.inventory_id == inventory_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class Scope1EntryRepository(_ScopeRepoMixin, _BaseRepo):
    model = Scope1Entry


class Scope2EntryRepository(_ScopeRepoMixin, _BaseRepo):
    model = Scope2Entry


class Scope3EntryRepository(_ScopeRepoMixin, _BaseRepo):
    model = Scope3Entry


# ── Targets ───────────────────────────────────────────────────────────────


class TargetRepository(_BaseRepo):
    """Data access for CarbonTarget."""

    model = CarbonTarget

    async def targets_for_project(
        self,
        project_id: uuid.UUID,
    ) -> list[CarbonTarget]:
        stmt = (
            select(CarbonTarget).where(CarbonTarget.project_id == project_id).order_by(CarbonTarget.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Reports ───────────────────────────────────────────────────────────────


class SustainabilityReportRepository(_BaseRepo):
    """Data access for SustainabilityReport."""

    model = SustainabilityReport

    async def reports_for_project(
        self,
        project_id: uuid.UUID,
    ) -> list[SustainabilityReport]:
        stmt = (
            select(SustainabilityReport)
            .where(SustainabilityReport.project_id == project_id)
            .order_by(SustainabilityReport.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
