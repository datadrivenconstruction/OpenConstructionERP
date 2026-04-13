"""Tasks data access layer."""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.models import Task


class TaskRepository:
    """Data access for Task models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        return await self.session.get(Task, task_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        current_user_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
        task_type: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        responsible_id: str | None = None,
        meeting_id: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Task], int]:
        base = select(Task).where(Task.project_id == project_id)

        # Private task filtering: only the creator can see private tasks
        if current_user_id is not None:
            base = base.where(
                or_(
                    Task.is_private == False,  # noqa: E712
                    Task.created_by == current_user_id,
                )
            )
        else:
            base = base.where(Task.is_private == False)  # noqa: E712

        if task_type is not None:
            base = base.where(Task.task_type == task_type)
        if status is not None:
            base = base.where(Task.status == status)
        if priority is not None:
            base = base.where(Task.priority == priority)
        if responsible_id is not None:
            base = base.where(Task.responsible_id == responsible_id)
        if meeting_id is not None:
            base = base.where(Task.meeting_id == meeting_id)

        # Free-text search across title + description + result fields.
        # Uses ILIKE for case-insensitive matching (works on both PG and SQLite).
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            base = base.where(
                or_(
                    Task.title.ilike(pattern),
                    Task.description.ilike(pattern),
                    Task.result.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Task.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_for_user(
        self,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Task], int]:
        """List tasks assigned to or created by a specific user.

        Private tasks are included only when the requesting user is the creator.
        """
        base = select(Task).where(
            or_(
                Task.responsible_id == user_id,
                # Include private tasks created by this user
                Task.created_by == user_id,
            )
        ).where(
            or_(
                Task.is_private == False,  # noqa: E712
                Task.created_by == user_id,
            )
        )
        if status is not None:
            base = base.where(Task.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Task.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, task: Task) -> Task:
        self.session.add(task)
        await self.session.flush()
        return task

    async def update_fields(self, task_id: uuid.UUID, **fields: object) -> None:
        stmt = update(Task).where(Task.id == task_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, task_id: uuid.UUID) -> None:
        task = await self.get_by_id(task_id)
        if task is not None:
            await self.session.delete(task)
            await self.session.flush()
