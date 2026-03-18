"""Project data access layer.

All database queries for projects live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project


class ProjectRepository:
    """Data access for Project model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        """Get project by ID."""
        return await self.session.get(Project, project_id)

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Project], int]:
        """List projects for a user with pagination. Returns (projects, total_count)."""
        base = select(Project).where(Project.owner_id == owner_id)
        if status is not None:
            base = base.where(Project.status == status)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(Project.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        projects = list(result.scalars().all())

        return projects, total

    async def create(self, project: Project) -> Project:
        """Insert a new project."""
        self.session.add(project)
        await self.session.flush()
        return project

    async def update_fields(self, project_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a project."""
        stmt = update(Project).where(Project.id == project_id).values(**fields)
        await self.session.execute(stmt)

    async def delete(self, project_id: uuid.UUID) -> None:
        """Hard delete a project."""
        project = await self.get_by_id(project_id)
        if project is not None:
            await self.session.delete(project)
            await self.session.flush()

    async def count_for_user(self, owner_id: uuid.UUID) -> int:
        """Total number of projects for a user."""
        stmt = select(func.count()).select_from(
            select(Project).where(Project.owner_id == owner_id).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()
