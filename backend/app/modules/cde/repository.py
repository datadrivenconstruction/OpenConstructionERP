"""‌⁠‍CDE data access layer.

All database queries for document containers and revisions live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cde.models import DocumentContainer, DocumentRevision


class ContainerRepository:
    """‌⁠‍Data access for DocumentContainer models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, container_id: uuid.UUID) -> DocumentContainer | None:
        """‌⁠‍Get container by ID."""
        return await self.session.get(DocumentContainer, container_id)

    async def get_by_code_and_project(
        self,
        project_id: uuid.UUID,
        container_code: str,
    ) -> DocumentContainer | None:
        """Get container by code within a project (uniqueness check)."""
        stmt = select(DocumentContainer).where(
            DocumentContainer.project_id == project_id,
            DocumentContainer.container_code == container_code,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        cde_state: str | None = None,
        discipline_code: str | None = None,
    ) -> tuple[list[DocumentContainer], int]:
        """List containers for a project with pagination and filters."""
        base = select(DocumentContainer).where(DocumentContainer.project_id == project_id)
        if cde_state is not None:
            base = base.where(DocumentContainer.cde_state == cde_state)
        if discipline_code is not None:
            base = base.where(DocumentContainer.discipline_code == discipline_code)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DocumentContainer.container_code.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, container: DocumentContainer) -> DocumentContainer:
        """Insert a new container."""
        self.session.add(container)
        await self.session.flush()
        return container

    async def update_fields(self, container_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a container."""
        stmt = update(DocumentContainer).where(DocumentContainer.id == container_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        """Compute aggregate statistics for a project's CDE containers.

        Returns dict with keys: total, by_state, by_discipline, latest_revisions.
        """
        # Total count
        total_stmt = (
            select(func.count()).select_from(DocumentContainer).where(DocumentContainer.project_id == project_id)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()

        # Count by state
        state_stmt = (
            select(DocumentContainer.cde_state, func.count())
            .where(DocumentContainer.project_id == project_id)
            .group_by(DocumentContainer.cde_state)
        )
        state_rows = (await self.session.execute(state_stmt)).all()
        by_state = {row[0]: row[1] for row in state_rows}

        # Count by discipline
        disc_stmt = (
            select(
                func.coalesce(DocumentContainer.discipline_code, "other"),
                func.count(),
            )
            .where(DocumentContainer.project_id == project_id)
            .group_by(func.coalesce(DocumentContainer.discipline_code, "other"))
        )
        disc_rows = (await self.session.execute(disc_stmt)).all()
        by_discipline = {row[0]: row[1] for row in disc_rows}

        # Count containers that have at least one revision (latest_revisions)
        rev_stmt = (
            select(func.count(func.distinct(DocumentRevision.container_id)))
            .select_from(DocumentRevision)
            .join(
                DocumentContainer,
                DocumentRevision.container_id == DocumentContainer.id,
            )
            .where(DocumentContainer.project_id == project_id)
        )
        latest_revisions = (await self.session.execute(rev_stmt)).scalar_one()

        return {
            "total": total,
            "by_state": by_state,
            "by_discipline": by_discipline,
            "latest_revisions": latest_revisions,
        }


class RevisionRepository:
    """Data access for DocumentRevision models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, revision_id: uuid.UUID) -> DocumentRevision | None:
        """Get revision by ID."""
        return await self.session.get(DocumentRevision, revision_id)

    async def list_for_container(
        self,
        container_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DocumentRevision], int]:
        """List revisions for a container with pagination."""
        base = select(DocumentRevision).where(DocumentRevision.container_id == container_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DocumentRevision.revision_number.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def next_revision_number(self, container_id: uuid.UUID) -> int:
        """Get the next revision number for a container."""
        stmt = select(func.coalesce(func.max(DocumentRevision.revision_number), 0)).where(
            DocumentRevision.container_id == container_id
        )
        current_max = (await self.session.execute(stmt)).scalar_one()
        return current_max + 1

    async def create(self, revision: DocumentRevision) -> DocumentRevision:
        """Insert a new revision."""
        self.session.add(revision)
        await self.session.flush()
        return revision

    async def update_fields(self, revision_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a revision."""
        stmt = update(DocumentRevision).where(DocumentRevision.id == revision_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()
