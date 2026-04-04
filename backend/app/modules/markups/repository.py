"""Markups & Annotations data access layer.

All database queries for markups, scale configs, and stamp templates live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.markups.models import Markup, ScaleConfig, StampTemplate


class MarkupRepository:
    """Data access for Markup models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, markup_id: uuid.UUID) -> Markup | None:
        """Get markup by ID."""
        return await self.session.get(Markup, markup_id)

    async def list_for_document(
        self,
        document_id: str,
        *,
        page: int | None = None,
        type_filter: str | None = None,
        status_filter: str | None = None,
    ) -> list[Markup]:
        """List markups for a specific document with optional filters."""
        stmt = select(Markup).where(Markup.document_id == document_id)
        if page is not None:
            stmt = stmt.where(Markup.page == page)
        if type_filter is not None:
            stmt = stmt.where(Markup.type == type_filter)
        if status_filter is not None:
            stmt = stmt.where(Markup.status == status_filter)
        stmt = stmt.order_by(Markup.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        type_filter: str | None = None,
        status_filter: str | None = None,
        document_id: str | None = None,
        page: int | None = None,
    ) -> tuple[list[Markup], int]:
        """List markups for a project with pagination and filters."""
        base = select(Markup).where(Markup.project_id == project_id)
        if document_id is not None:
            base = base.where(Markup.document_id == document_id)
        if page is not None:
            base = base.where(Markup.page == page)
        if type_filter is not None:
            base = base.where(Markup.type == type_filter)
        if status_filter is not None:
            base = base.where(Markup.status == status_filter)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Markup.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def summary_for_project(
        self, project_id: uuid.UUID
    ) -> dict[str, dict[str, int]]:
        """Get markup counts grouped by type and status for a project."""
        items = await self.all_for_project(project_id)

        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for item in items:
            by_type[item.type] = by_type.get(item.type, 0) + 1
            by_status[item.status] = by_status.get(item.status, 0) + 1

        return {"by_type": by_type, "by_status": by_status, "total": len(items)}

    async def search(
        self,
        project_id: uuid.UUID,
        query: str,
    ) -> list[Markup]:
        """Search markups by text content in label and text fields."""
        pattern = f"%{query}%"
        stmt = (
            select(Markup)
            .where(Markup.project_id == project_id)
            .where(
                or_(
                    Markup.label.ilike(pattern),
                    Markup.text.ilike(pattern),
                )
            )
            .order_by(Markup.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def all_for_project(self, project_id: uuid.UUID) -> list[Markup]:
        """Return all markups for a project (used for summary/export)."""
        stmt = select(Markup).where(Markup.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, item: Markup) -> Markup:
        """Insert a new markup."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def create_bulk(self, items: list[Markup]) -> list[Markup]:
        """Insert multiple markups at once."""
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def update_fields(self, markup_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a markup."""
        stmt = update(Markup).where(Markup.id == markup_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, markup_id: uuid.UUID) -> None:
        """Hard delete a markup."""
        item = await self.get_by_id(markup_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()


class ScaleConfigRepository:
    """Data access for ScaleConfig models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, config_id: uuid.UUID) -> ScaleConfig | None:
        """Get scale config by ID."""
        return await self.session.get(ScaleConfig, config_id)

    async def list_for_document(
        self,
        document_id: str,
        *,
        page: int | None = None,
    ) -> list[ScaleConfig]:
        """List scale configs for a document, optionally filtered by page."""
        stmt = select(ScaleConfig).where(ScaleConfig.document_id == document_id)
        if page is not None:
            stmt = stmt.where(ScaleConfig.page == page)
        stmt = stmt.order_by(ScaleConfig.page.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, item: ScaleConfig) -> ScaleConfig:
        """Insert a new scale config."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete(self, config_id: uuid.UUID) -> None:
        """Hard delete a scale config."""
        item = await self.get_by_id(config_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()


class StampTemplateRepository:
    """Data access for StampTemplate models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, template_id: uuid.UUID) -> StampTemplate | None:
        """Get stamp template by ID."""
        return await self.session.get(StampTemplate, template_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID | None,
    ) -> list[StampTemplate]:
        """List stamp templates: predefined (global) + project-specific."""
        stmt = select(StampTemplate).where(
            or_(
                StampTemplate.category == "predefined",
                StampTemplate.project_id == project_id,
            )
        )
        stmt = stmt.where(StampTemplate.is_active.is_(True))
        stmt = stmt.order_by(StampTemplate.category.asc(), StampTemplate.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_predefined(self) -> list[StampTemplate]:
        """List all predefined stamp templates."""
        stmt = (
            select(StampTemplate)
            .where(StampTemplate.category == "predefined")
            .order_by(StampTemplate.name.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, item: StampTemplate) -> StampTemplate:
        """Insert a new stamp template."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, template_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a stamp template."""
        stmt = (
            update(StampTemplate)
            .where(StampTemplate.id == template_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, template_id: uuid.UUID) -> None:
        """Hard delete a stamp template."""
        item = await self.get_by_id(template_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()
