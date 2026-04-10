"""Tasks service — business logic for task management.

- Event publishing on create/update/delete
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.tasks.models import Task
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskStatsResponse, TaskUpdate

logger = logging.getLogger(__name__)
_logger_ev = logging.getLogger(__name__ + ".events")
_logger_audit = logging.getLogger(__name__ + ".audit")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


async def _safe_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Best-effort audit log — never blocks the caller on failure."""
    try:
        from app.core.audit import audit_log

        await audit_log(
            session,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            details=details,
        )
    except Exception:
        _logger_audit.debug("Audit log write skipped for %s %s", action, entity_type)

# ── Allowed task status transitions ───────────────────────────────────────────

_TASK_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"open"},
    "open": {"in_progress", "completed", "draft"},
    "in_progress": {"completed", "open"},
    # Allow reopening completed tasks for rework / scope change scenarios.
    # The audit log + event bus provide traceability for state changes.
    "completed": {"open", "in_progress"},
}


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

        await _safe_audit(
            self.session,
            action="create",
            entity_type="task",
            entity_id=str(task.id),
            user_id=user_id,
            details={
                "title": data.title[:100],
                "project_id": str(data.project_id),
                "task_type": data.task_type,
            },
        )

        logger.info("Task created: %s (%s) for project %s", task.title[:40], data.task_type, data.project_id)

        # Publish task.assigned event so notification handlers fire
        if data.responsible_id:
            await _safe_publish(
                "task.assigned",
                {
                    "project_id": str(data.project_id),
                    "task_id": str(task.id),
                    "title": data.title,
                    "responsible_id": str(data.responsible_id),
                    "assigned_by": user_id or "",
                },
                source_module="oe_tasks",
            )

        return task

    async def get_task(
        self,
        task_id: uuid.UUID,
        current_user_id: str | None = None,
    ) -> Task:
        task = await self.repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        # Enforce private task visibility
        if task.is_private and task.created_by != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        return task

    async def list_tasks(
        self,
        project_id: uuid.UUID,
        *,
        current_user_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
        task_type: str | None = None,
        status_filter: str | None = None,
        priority: str | None = None,
        responsible_id: str | None = None,
        meeting_id: str | None = None,
    ) -> tuple[list[Task], int]:
        return await self.repo.list_for_project(
            project_id,
            current_user_id=current_user_id,
            offset=offset,
            limit=limit,
            task_type=task_type,
            status=status_filter,
            priority=priority,
            responsible_id=responsible_id,
            meeting_id=meeting_id,
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
        current_user_id: str | None = None,
    ) -> Task:
        task = await self.get_task(task_id, current_user_id=current_user_id)

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

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        if new_status is not None and new_status != task.status:
            allowed = _TASK_STATUS_TRANSITIONS.get(task.status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition task from '{task.status}' to '{new_status}'. "
                        f"Allowed transitions: {', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        if not fields:
            return task

        # Detect reassignment so we can fire task.assigned
        old_responsible = str(task.responsible_id) if task.responsible_id else None
        new_responsible = fields.get("responsible_id")

        await self.repo.update_fields(task_id, **fields)
        await self.session.refresh(task)

        await _safe_audit(
            self.session,
            action="update",
            entity_type="task",
            entity_id=str(task_id),
            user_id=current_user_id,
            details={"title": task.title[:100], "updated_fields": list(fields.keys())},
        )

        logger.info("Task updated: %s (fields=%s)", task_id, list(fields.keys()))

        # Fire task.assigned when responsible_id changes to a new user
        if (
            new_responsible is not None
            and str(new_responsible) != old_responsible
        ):
            await _safe_publish(
                "task.assigned",
                {
                    "project_id": str(task.project_id),
                    "task_id": str(task_id),
                    "title": task.title,
                    "responsible_id": str(new_responsible),
                    "assigned_by": current_user_id or "",
                },
                source_module="oe_tasks",
            )

        return task

    async def delete_task(
        self,
        task_id: uuid.UUID,
        current_user_id: str | None = None,
    ) -> None:
        await self.get_task(task_id, current_user_id=current_user_id)
        await self.repo.delete(task_id)
        logger.info("Task deleted: %s", task_id)

    async def complete_task(
        self,
        task_id: uuid.UUID,
        result: str | None = None,
        current_user_id: str | None = None,
    ) -> Task:
        """Mark a task as completed with optional result."""
        task = await self.get_task(task_id, current_user_id=current_user_id)
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

    async def get_stats(
        self,
        project_id: uuid.UUID,
        current_user_id: str | None = None,
    ) -> TaskStatsResponse:
        """Compute summary statistics for all tasks in a project.

        Includes total, breakdowns by status/type/priority, overdue count,
        and average checklist progress across non-completed tasks.
        """
        from collections import defaultdict
        from datetime import UTC, datetime

        from sqlalchemy import or_, select

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")

        base = select(Task).where(Task.project_id == project_id)
        # Respect private task visibility
        if current_user_id is not None:
            base = base.where(
                or_(
                    Task.is_private == False,  # noqa: E712
                    Task.created_by == current_user_id,
                )
            )
        else:
            base = base.where(Task.is_private == False)  # noqa: E712

        result = await self.session.execute(base)
        tasks = list(result.scalars().all())

        total = len(tasks)
        by_status: dict[str, int] = defaultdict(int)
        by_type: dict[str, int] = defaultdict(int)
        by_priority: dict[str, int] = defaultdict(int)
        overdue_count = 0
        completed_count = 0
        checklist_progress_values: list[float] = []

        for task in tasks:
            by_status[task.status] += 1
            by_type[task.task_type] += 1
            by_priority[task.priority] += 1

            if task.status == "completed":
                completed_count += 1

            # Overdue: not completed + due_date in the past
            if task.status != "completed" and task.due_date:
                try:
                    if str(task.due_date) < today_str:
                        overdue_count += 1
                except (TypeError, ValueError):
                    pass

            # Checklist progress for non-completed tasks
            if task.status != "completed" and task.checklist:
                items = task.checklist
                total_items = len(items)
                if total_items > 0:
                    done = sum(
                        1 for c in items if isinstance(c, dict) and c.get("completed")
                    )
                    checklist_progress_values.append(done / total_items * 100)

        avg_checklist_progress: float | None = None
        if checklist_progress_values:
            avg_checklist_progress = round(
                sum(checklist_progress_values) / len(checklist_progress_values), 1
            )

        return TaskStatsResponse(
            total=total,
            by_status=dict(by_status),
            by_type=dict(by_type),
            by_priority=dict(by_priority),
            overdue_count=overdue_count,
            completed_count=completed_count,
            avg_checklist_progress=avg_checklist_progress,
        )

    async def list_upcoming_tasks(
        self,
        project_id: uuid.UUID,
        *,
        days_ahead: int = 7,
        responsible_id: str | None = None,
    ) -> list[Task]:
        """Return non-completed tasks with due_date within ``days_ahead`` days.

        Used by reminder/notification workflows. Excludes tasks already overdue
        (those are handled separately via get_stats overdue_count).

        Args:
            project_id: Scope to this project.
            days_ahead: Window in days (default 7).
            responsible_id: Optional — filter to a specific assignee.
        """
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import and_, select

        today = datetime.now(UTC).date()
        horizon = today + timedelta(days=days_ahead)
        today_str = today.isoformat()
        horizon_str = horizon.isoformat()

        stmt = select(Task).where(
            and_(
                Task.project_id == project_id,
                Task.status != "completed",
                Task.due_date.isnot(None),
                Task.due_date >= today_str,
                Task.due_date <= horizon_str,
            )
        )
        if responsible_id:
            stmt = stmt.where(Task.responsible_id == responsible_id)
        stmt = stmt.order_by(Task.due_date)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
