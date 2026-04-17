"""DWG Takeoff data access layer.

All database queries for drawings, drawing versions, and annotations live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dwg_takeoff.models import (
    DwgAnnotation,
    DwgDrawing,
    DwgDrawingVersion,
    DwgEntityGroup,
)


class DwgDrawingRepository:
    """Data access for DwgDrawing models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, drawing_id: uuid.UUID) -> DwgDrawing | None:
        """Get drawing by ID."""
        return await self.session.get(DwgDrawing, drawing_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[DwgDrawing], int]:
        """List drawings for a project with pagination and filters."""
        base = select(DwgDrawing).where(DwgDrawing.project_id == project_id)
        if status_filter is not None:
            base = base.where(DwgDrawing.status == status_filter)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DwgDrawing.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: DwgDrawing) -> DwgDrawing:
        """Insert a new drawing."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, drawing_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a drawing."""
        stmt = update(DwgDrawing).where(DwgDrawing.id == drawing_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, drawing_id: uuid.UUID) -> None:
        """Hard delete a drawing."""
        item = await self.get_by_id(drawing_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()


class DwgDrawingVersionRepository:
    """Data access for DwgDrawingVersion models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, version_id: uuid.UUID) -> DwgDrawingVersion | None:
        """Get drawing version by ID."""
        return await self.session.get(DwgDrawingVersion, version_id)

    async def get_latest_for_drawing(self, drawing_id: uuid.UUID) -> DwgDrawingVersion | None:
        """Get the latest version for a drawing."""
        stmt = (
            select(DwgDrawingVersion)
            .where(DwgDrawingVersion.drawing_id == drawing_id)
            .order_by(DwgDrawingVersion.version_number.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_drawing(self, drawing_id: uuid.UUID) -> list[DwgDrawingVersion]:
        """List all versions for a drawing."""
        stmt = (
            select(DwgDrawingVersion)
            .where(DwgDrawingVersion.drawing_id == drawing_id)
            .order_by(DwgDrawingVersion.version_number.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_next_version_number(self, drawing_id: uuid.UUID) -> int:
        """Get the next version number for a drawing."""
        stmt = select(func.max(DwgDrawingVersion.version_number)).where(
            DwgDrawingVersion.drawing_id == drawing_id
        )
        result = (await self.session.execute(stmt)).scalar_one_or_none()
        return (result or 0) + 1

    async def create(self, item: DwgDrawingVersion) -> DwgDrawingVersion:
        """Insert a new drawing version."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, version_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a drawing version."""
        stmt = update(DwgDrawingVersion).where(DwgDrawingVersion.id == version_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


class DwgAnnotationRepository:
    """Data access for DwgAnnotation models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, annotation_id: uuid.UUID) -> DwgAnnotation | None:
        """Get annotation by ID."""
        return await self.session.get(DwgAnnotation, annotation_id)

    async def list_for_drawing(
        self,
        drawing_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        annotation_type: str | None = None,
    ) -> tuple[list[DwgAnnotation], int]:
        """List annotations for a drawing with pagination and filters."""
        base = select(DwgAnnotation).where(DwgAnnotation.drawing_id == drawing_id)
        if annotation_type is not None:
            base = base.where(DwgAnnotation.annotation_type == annotation_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DwgAnnotation.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def list_pins_for_drawing(self, drawing_id: uuid.UUID) -> list[DwgAnnotation]:
        """List annotations that are linked to tasks or punchlist items."""
        stmt = (
            select(DwgAnnotation)
            .where(DwgAnnotation.drawing_id == drawing_id)
            .where(
                (DwgAnnotation.linked_task_id.isnot(None))
                | (DwgAnnotation.linked_punch_item_id.isnot(None))
            )
            .order_by(DwgAnnotation.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, item: DwgAnnotation) -> DwgAnnotation:
        """Insert a new annotation."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, annotation_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an annotation."""
        stmt = update(DwgAnnotation).where(DwgAnnotation.id == annotation_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, annotation_id: uuid.UUID) -> None:
        """Hard delete an annotation."""
        item = await self.get_by_id(annotation_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()


class DwgEntityGroupRepository:
    """Data access for DwgEntityGroup models (RFC 11)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, group_id: uuid.UUID) -> DwgEntityGroup | None:
        """Get entity group by ID."""
        return await self.session.get(DwgEntityGroup, group_id)

    async def list_for_drawing(
        self,
        drawing_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[DwgEntityGroup], int]:
        """List saved groups for a drawing with pagination."""
        base = select(DwgEntityGroup).where(DwgEntityGroup.drawing_id == drawing_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DwgEntityGroup.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: DwgEntityGroup) -> DwgEntityGroup:
        """Insert a new entity group."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete(self, group_id: uuid.UUID) -> None:
        """Hard delete an entity group."""
        item = await self.get_by_id(group_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()
