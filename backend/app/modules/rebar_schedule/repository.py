# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Rebar schedule data access layer.

Every query for imports and shapes lives here. No business logic.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rebar_schedule.models import RebarScheduleImport, RebarShape


class RebarImportRepository:
    """Data access for imported ABS files."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, import_id: uuid.UUID) -> RebarScheduleImport | None:
        """Get one import by its id."""
        return await self.session.get(RebarScheduleImport, import_id)

    async def get_by_content(self, project_id: uuid.UUID, sha256: str) -> RebarScheduleImport | None:
        """Get an import of the same bytes into the same project, if any."""
        stmt = select(RebarScheduleImport).where(
            RebarScheduleImport.project_id == project_id,
            RebarScheduleImport.content_sha256 == sha256,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        validation_status: str | None = None,
    ) -> tuple[list[RebarScheduleImport], int]:
        """List a project's imports, newest first, with the total count."""
        base = select(RebarScheduleImport).where(RebarScheduleImport.project_id == project_id)
        if validation_status is not None:
            base = base.where(RebarScheduleImport.validation_status == validation_status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(RebarScheduleImport.created_at.desc()).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total)

    async def add(self, record: RebarScheduleImport) -> RebarScheduleImport:
        """Stage a new import row."""
        self.session.add(record)
        await self.session.flush()
        return record

    async def delete(self, record: RebarScheduleImport) -> None:
        """Delete an import. Its shapes go with it by cascade."""
        await self.session.delete(record)
        await self.session.flush()


class RebarShapeRepository:
    """Data access for bending shapes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, shape_id: uuid.UUID) -> RebarShape | None:
        """Get one shape by its id."""
        return await self.session.get(RebarShape, shape_id)

    async def add_all(self, shapes: list[RebarShape]) -> None:
        """Stage a batch of shapes."""
        self.session.add_all(shapes)
        await self.session.flush()

    async def list_for_import(
        self,
        import_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        super_group: str | None = None,
        diameter_mm: float | None = None,
    ) -> tuple[list[RebarShape], int]:
        """List one import's shapes in source order, with the total count."""
        base = select(RebarShape).where(RebarShape.import_id == import_id)
        if super_group is not None:
            base = base.where(RebarShape.super_group == super_group)
        if diameter_mm is not None:
            base = base.where(RebarShape.diameter_mm == diameter_mm)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(RebarShape.line_no).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        drawing_ref: str | None = None,
        position: str | None = None,
    ) -> tuple[list[RebarShape], int]:
        """List a project's shapes across every import."""
        base = select(RebarShape).where(RebarShape.project_id == project_id)
        if drawing_ref is not None:
            base = base.where(RebarShape.drawing_ref == drawing_ref)
        if position is not None:
            base = base.where(RebarShape.position == position)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(RebarShape.drawing_ref, RebarShape.line_no).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total)

    async def weight_by_diameter(self, import_id: uuid.UUID) -> list[tuple[str, int, float]]:
        """Total bars and weight per bar diameter, for a cutting summary.

        Returns:
            One ``(diameter, bars, weight_kg)`` triple per diameter, ordered by
            diameter. The diameter is returned as text because the standard
            allows a decimal diameter and the frontend groups on the label.
        """
        stmt = (
            select(
                RebarShape.diameter_mm,
                func.sum(RebarShape.quantity),
                func.sum(RebarShape.quantity * RebarShape.weight_kg),
            )
            .where(RebarShape.import_id == import_id, RebarShape.diameter_mm.is_not(None))
            .group_by(RebarShape.diameter_mm)
            .order_by(RebarShape.diameter_mm)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(str(diameter), int(bars or 0), float(weight or 0)) for diameter, bars, weight in rows]

    async def delete_for_import(self, import_id: uuid.UUID) -> int:
        """Delete every shape of one import. Returns how many went."""
        result = await self.session.execute(delete(RebarShape).where(RebarShape.import_id == import_id))
        await self.session.flush()
        return int(result.rowcount or 0)
