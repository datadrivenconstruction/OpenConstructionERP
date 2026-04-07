"""Inspections data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inspections.models import QualityInspection


class InspectionRepository:
    """Data access for QualityInspection models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, inspection_id: uuid.UUID) -> QualityInspection | None:
        """Get inspection by ID."""
        return await self.session.get(QualityInspection, inspection_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        inspection_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[QualityInspection], int]:
        """List inspections for a project with pagination and filters."""
        base = select(QualityInspection).where(QualityInspection.project_id == project_id)
        if inspection_type is not None:
            base = base.where(QualityInspection.inspection_type == inspection_type)
        if status is not None:
            base = base.where(QualityInspection.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(QualityInspection.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def next_inspection_number(self, project_id: uuid.UUID) -> str:
        """Generate the next inspection number (INS-001, INS-002, ...)."""
        stmt = (
            select(func.count())
            .select_from(QualityInspection)
            .where(QualityInspection.project_id == project_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"INS-{count + 1:03d}"

    async def create(self, inspection: QualityInspection) -> QualityInspection:
        """Insert a new inspection."""
        self.session.add(inspection)
        await self.session.flush()
        return inspection

    async def update_fields(self, inspection_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an inspection."""
        stmt = (
            update(QualityInspection)
            .where(QualityInspection.id == inspection_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, inspection_id: uuid.UUID) -> None:
        """Hard delete an inspection."""
        inspection = await self.get_by_id(inspection_id)
        if inspection is not None:
            await self.session.delete(inspection)
            await self.session.flush()
