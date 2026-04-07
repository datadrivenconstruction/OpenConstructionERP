"""Tasks service — business logic for task management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.models import Task
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskUpdate

logger = logging.getLogger(__name__)


class TaskService:
    """Business logic for task operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TaskRepository(session)

    async def create_task(
        self,
        data: TaskCreate,
        user_id: str | None = None,
    ) -> Task:
        """Create a new task."""
        checklist = [entry.model_dump() for entry in data.checklist]

        task = Task(
            project_id=data.project_id,
            task_type=data.task_type,
            title=data.title,
            description=data.description,
            checklist=checklist,
            responsible_id=data.responsible_id,
            persons_involved=data.persons_involved,
            due_date=data.due_date,
            milestone_id=data.milestone_id,
            meeting_id=data.meeting_id,
            status=data.status,
            priority=data.priority,
            result=data.result,
            is_private=data.is_private,
            created_by=user_id,
            metadata_=data.metadata,
        )
        task = await self.repo.create(task)
        logger.info("Task created: %s (%s) for project %s", task.title[:40], data.task_type, data.project_id)
        return task

    async def get_task(self, task_id: uuid.UUID) -> Task:
        task = await self.repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        return task

    async def list_tasks(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        task_type: str | None = None,
        status_filter: str | None = None,
        priority: str | None = None,
        responsible_id: str | None = None,
    ) -> tuple[list[Task], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            task_type=task_type,
            status=status_filter,
            priority=priority,
            responsible_id=responsible_id,
        )

    async def list_my_tasks(
        self,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[Task], int]:
        """List tasks assigned to the current user."""
        return await self.repo.list_for_user(
            user_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def update_task(
        self,
        task_id: uuid.UUID,
        data: TaskUpdate,
    ) -> Task:
        task = await self.get_task(task_id)

        if task.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit a completed task",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "checklist" in fields and fields["checklist"] is not None:
            fields["checklist"] = [
                entry.model_dump() if hasattr(entry, "model_dump") else entry
                for entry in fields["checklist"]
            ]

        if not fields:
            return task

        await self.repo.update_fields(task_id, **fields)
        await self.session.refresh(task)
        logger.info("Task updated: %s (fields=%s)", task_id, list(fields.keys()))
        return task

    async def delete_task(self, task_id: uuid.UUID) -> None:
        await self.get_task(task_id)
        await self.repo.delete(task_id)
        logger.info("Task deleted: %s", task_id)

    async def complete_task(
        self,
        task_id: uuid.UUID,
        result: str | None = None,
    ) -> Task:
        """Mark a task as completed with optional result."""
        task = await self.get_task(task_id)
        if task.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is already completed",
            )

        fields: dict[str, Any] = {"status": "completed"}
        if result is not None:
            fields["result"] = result

        await self.repo.update_fields(task_id, **fields)
        await self.session.refresh(task)
        logger.info("Task completed: %s", task_id)
        return task
