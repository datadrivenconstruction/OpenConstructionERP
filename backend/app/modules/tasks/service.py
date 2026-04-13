"""Tasks service — business logic for task management.

- Event publishing on create/update/delete
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
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

        # Validate dependency: predecessor must exist in same project
        if data.depends_on:
            predecessor = await self.repo.get_by_id(data.depends_on)
            if predecessor is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Dependency task {data.depends_on} not found",
                )
            if predecessor.project_id != data.project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Dependency task must belong to the same project",
                )

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
            depends_on=data.depends_on,
            bim_element_ids=list(data.bim_element_ids or []),
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

        # Publish lifecycle event for vector indexing + other subscribers
        await _safe_publish(
            "tasks.task.created",
            {
                "task_id": str(task.id),
                "project_id": str(data.project_id),
                "task_type": data.task_type,
            },
            source_module="oe_tasks",
        )

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
        search: str | None = None,
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
            search=search,
        )

    async def update_bim_links(
        self,
        task_id: uuid.UUID,
        bim_element_ids: list[str],
        *,
        current_user_id: str | None = None,
    ) -> Task:
        """Replace the full set of BIM element ids linked to a task.

        Idempotent set semantics — the incoming list overwrites whatever
        was previously stored. De-duplication is applied while preserving
        first-seen order so the viewer sees a stable list on re-render.
        """
        task = await self.get_task(task_id, current_user_id=current_user_id)

        seen: set[str] = set()
        deduped: list[str] = []
        for raw in bim_element_ids or []:
            if raw is None:
                continue
            val = str(raw).strip()
            if not val or val in seen:
                continue
            seen.add(val)
            deduped.append(val)

        await self.repo.update_fields(task_id, bim_element_ids=deduped)
        await self.session.refresh(task)

        await _safe_audit(
            self.session,
            action="update",
            entity_type="task",
            entity_id=str(task_id),
            user_id=current_user_id,
            details={
                "title": task.title[:100],
                "updated_fields": ["bim_element_ids"],
                "bim_element_count": len(deduped),
            },
        )
        logger.info(
            "Task %s bim_element_ids updated: %d element(s)",
            task_id,
            len(deduped),
        )
        return task

    async def get_tasks_for_bim_element(
        self,
        bim_element_id: str,
        *,
        project_id: uuid.UUID | None = None,
        current_user_id: str | None = None,
    ) -> list[Task]:
        """Return all tasks that include ``bim_element_id`` in their list.

        Uses the PostgreSQL JSONB ``@>`` containment operator on PG and
        falls back to a Python-side filter on SQLite. Dialect is detected
        from ``session.bind.dialect.name``.
        """
        element_id = str(bim_element_id).strip()
        if not element_id:
            return []

        bind = self.session.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "") or ""

        stmt = select(Task)
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)

        if dialect_name == "postgresql":
            # JSONB ``@>`` containment: rows where bim_element_ids ⊇ [element_id]
            stmt = stmt.where(Task.bim_element_ids.contains([element_id]))
            result = await self.session.execute(stmt)
            tasks = list(result.scalars().all())
        else:
            # SQLite (and anything else) — filter in Python. The query is
            # project-scoped when possible so we don't pull the entire table.
            result = await self.session.execute(stmt)
            all_tasks = list(result.scalars().all())
            tasks = [
                t
                for t in all_tasks
                if t.bim_element_ids
                and element_id in [str(x) for x in t.bim_element_ids]
            ]

        # Respect private task visibility
        if current_user_id is not None:
            tasks = [
                t
                for t in tasks
                if not t.is_private or (t.created_by == current_user_id)
            ]
        else:
            tasks = [t for t in tasks if not t.is_private]

        return tasks

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

        # Validate dependency change: prevent self-reference and cycles
        if "depends_on" in fields and fields["depends_on"] is not None:
            new_dep_id = fields["depends_on"]
            if new_dep_id == task_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Task cannot depend on itself",
                )
            # Walk up the dependency chain to detect cycles
            visited: set[uuid.UUID] = {task_id}
            cur_id = new_dep_id
            while cur_id is not None:
                if cur_id in visited:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Dependency would create a cycle",
                    )
                visited.add(cur_id)
                pred = await self.repo.get_by_id(cur_id)
                if pred is None or pred.project_id != task.project_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid dependency target",
                    )
                cur_id = pred.depends_on

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

        # Publish lifecycle event for vector indexing + other subscribers
        await _safe_publish(
            "tasks.task.updated",
            {
                "task_id": str(task_id),
                "project_id": str(task.project_id),
                "updated_fields": list(fields.keys()),
            },
            source_module="oe_tasks",
        )

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
        task = await self.get_task(task_id, current_user_id=current_user_id)
        project_id = str(task.project_id) if task.project_id else ""
        await self.repo.delete(task_id)
        logger.info("Task deleted: %s", task_id)

        # Publish lifecycle event for vector indexing + other subscribers
        await _safe_publish(
            "tasks.task.deleted",
            {
                "task_id": str(task_id),
                "project_id": project_id,
            },
            source_module="oe_tasks",
        )

    async def complete_task(
        self,
        task_id: uuid.UUID,
        result: str | None = None,
        current_user_id: str | None = None,
    ) -> Task:
        """Mark a task as completed with optional result.

        Enforces dependency guard: if this task has a ``depends_on`` predecessor
        that is not yet completed, the request is rejected with HTTP 409. This
        prevents skipping prerequisite work in a dependency chain.
        """
        task = await self.get_task(task_id, current_user_id=current_user_id)
        if task.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is already completed",
            )

        # Dependency guard
        if task.depends_on:
            predecessor = await self.repo.get_by_id(task.depends_on)
            if predecessor and predecessor.status != "completed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot complete: blocked by '{predecessor.title}' "
                        f"(status: {predecessor.status}). Complete it first."
                    ),
                )

        fields: dict[str, Any] = {"status": "completed"}
        if result is not None:
            fields["result"] = result

        await self.repo.update_fields(task_id, **fields)
        await self.session.refresh(task)
        logger.info("Task completed: %s", task_id)
        return task

    async def list_blockers(self, task_id: uuid.UUID) -> list[Task]:
        """Return tasks that are blocked by this task (have depends_on == task_id)."""
        from sqlalchemy import select

        stmt = select(Task).where(Task.depends_on == task_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
