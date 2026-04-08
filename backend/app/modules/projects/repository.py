"""Project data access layer.

All database queries for projects live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

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
        exclude_archived: bool = True,
        is_admin: bool = False,
    ) -> tuple[list[Project], int]:
        """List projects for a user with pagination. Returns (projects, total_count).

        Admins see all projects; regular users see only their own.
        Archived (soft-deleted) projects are excluded by default; pass an
        explicit `status` to override.
        """
        base = select(Project)
        if not is_admin:
            base = base.where(Project.owner_id == owner_id)
        if status is not None:
            base = base.where(Project.status == status)
        elif exclude_archived:
            base = base.where(Project.status != "archived")

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch — skip eager loading of relationships for list queries
        stmt = (
            base.options(
                noload(Project.wbs_nodes),
                noload(Project.milestones),
                noload(Project.children),
            )
            .order_by(Project.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
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
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, project_id: uuid.UUID) -> None:
        """Hard delete a project."""
        project = await self.get_by_id(project_id)
        if project is not None:
            await self.session.delete(project)
            await self.session.flush()

    async def count_for_user(self, owner_id: uuid.UUID) -> int:
        """Total number of projects for a user."""
        stmt = select(func.count()).select_from(select(Project).where(Project.owner_id == owner_id).subquery())
        return (await self.session.execute(stmt)).scalar_one()

    async def max_project_code_seq(self, prefix: str) -> int | None:
        """Find the maximum sequence number for project codes with the given prefix.

        Scans codes like ``PRJ-2026-0001`` and extracts the numeric suffix.
        Returns ``None`` if no matching codes exist.
        """
        stmt = select(Project.project_code).where(
            Project.project_code.isnot(None),
            Project.project_code.startswith(prefix),
        )
        result = await self.session.execute(stmt)
        codes = [row[0] for row in result.all()]

        if not codes:
            return None

        max_seq = 0
        prefix_len = len(prefix)
        for code in codes:
            try:
                seq = int(code[prefix_len:])
                if seq > max_seq:
                    max_seq = seq
            except (ValueError, IndexError):
                continue

        return max_seq if max_seq > 0 else None
