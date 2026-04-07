"""Tasks data access layer."""

import uuid

from sqlalchemy import func, select, update
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
        offset: int = 0,
        limit: int = 50,
        task_type: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        responsible_id: str | None = None,
    ) -> tuple[list[Task], int]:
        base = select(Task).where(Task.project_id == project_id)
        if task_type is not None:
            base = base.where(Task.task_type == task_type)
        if status is not None:
            base = base.where(Task.status == status)
        if priority is not None:
            base = base.where(Task.priority == priority)
        if responsible_id is not None:
            base = base.where(Task.responsible_id == responsible_id)

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
        """List tasks assigned to a specific user (responsible_id)."""
        base = select(Task).where(Task.responsible_id == user_id)
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
