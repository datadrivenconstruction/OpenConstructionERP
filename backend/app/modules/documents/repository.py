"""Document Management data access layer.

All database queries for documents live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document


class DocumentRepository:
    """Data access for Document models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        """Get document by ID."""
        return await self.session.get(Document, document_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Document], int]:
        """List documents for a project with pagination and filters."""
        base = select(Document).where(Document.project_id == project_id)
        if category is not None:
            base = base.where(Document.category == category)
        if search is not None:
            pattern = f"%{search}%"
            base = base.where(
                or_(
                    Document.name.ilike(pattern),
                    Document.description.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Document.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, document: Document) -> Document:
        """Insert a new document."""
        self.session.add(document)
        await self.session.flush()
        return document

    async def update_fields(self, document_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a document."""
        stmt = update(Document).where(Document.id == document_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, document_id: uuid.UUID) -> None:
        """Hard delete a document."""
        item = await self.get_by_id(document_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def all_for_project(self, project_id: uuid.UUID) -> list[Document]:
        """Return all documents for a project (used for summary)."""
        stmt = select(Document).where(Document.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def summary_for_project(
        self, project_id: uuid.UUID
    ) -> tuple[int, int, list[tuple[str, int]]]:
        """Return aggregated stats using SQL: (total_count, total_size, [(category, count)])."""
        # Total count and size
        totals_stmt = select(
            func.count(Document.id),
            func.coalesce(func.sum(Document.file_size), 0),
        ).where(Document.project_id == project_id)
        totals_row = (await self.session.execute(totals_stmt)).one()
        total_count: int = totals_row[0]
        total_size: int = totals_row[1]

        # Count by category
        cat_stmt = (
            select(Document.category, func.count(Document.id))
            .where(Document.project_id == project_id)
            .group_by(Document.category)
        )
        cat_rows = (await self.session.execute(cat_stmt)).all()

        return total_count, total_size, list(cat_rows)
