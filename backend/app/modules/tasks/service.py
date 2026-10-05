# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tasks service - business logic for task management.

- Event publishing on create/update/delete
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.academy_isolation import academy_mode_enabled, assert_users_can_access_project, filter_users_to_project
from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.tasks.models import Task
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskStatsResponse, TaskUpdate

logger = logging.getLogger(__name__)
_logger_ev = logging.getLogger(__name__ + ".events")
_logger_audit = logging.getLogger(__name__ + ".audit")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
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
    """Best-effort audit log - never blocks the caller on failure."""
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

        responsible_id = data.responsible_id
        metadata = dict(data.metadata or {})
        if data.assignee_contact_id is not None:
            contact_fields = await self._contact_assignee(data.assignee_contact_id, user_id)
            responsible_id = contact_fields.pop("responsible_id")
            metadata.update(contact_fields)

        # Academy mode: the people a task names must be in its project. A no-op
        # on a normal install.
        await assert_users_can_access_project(
            self.session, data.project_id, [responsible_id, *(data.persons_involved or [])]
        )

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
            # A task cannot be born already-completed while its predecessor
            # is still open - that would silently bypass the dependency
            # guard that complete_task() enforces on the normal path.
            if data.status == "completed" and predecessor.status != "completed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot create a completed task while its dependency "
                        f"'{predecessor.title}' (status: {predecessor.status}) "
                        f"is not completed."
                    ),
                )

        task = Task(
            project_id=data.project_id,
            task_type=data.task_type,
            title=data.title,
            description=data.description,
            checklist=checklist,
            responsible_id=responsible_id,
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
            metadata_=metadata,
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
        if responsible_id:
            await _safe_publish(
                "task.assigned",
                {
                    "project_id": str(data.project_id),
                    "task_id": str(task.id),
                    "title": data.title,
                    "responsible_id": str(responsible_id),
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

    async def resolve_assignee_names(
        self,
        tasks: list[Task],
    ) -> dict[str, str]:
        """Map ``responsible_id`` → user display name for a batch of tasks.

        One ``IN (...)`` query over the distinct assignee ids - avoids the
        N+1 the per-row name lookup would otherwise cause. Ids that don't
        resolve (deleted users, free-text-only assignees) are simply
        absent from the returned mapping so the caller can fall back to
        ``metadata.assignee_name``.

        In academy mode a name is resolved only for a user who is in the
        task's own project, so a row written around the assignee gate cannot
        print another learner's name.
        """
        ids: set[uuid.UUID] = set()
        by_project: dict[object, set[uuid.UUID]] = {}
        for t in tasks:
            if t.responsible_id:
                try:
                    uid = uuid.UUID(str(t.responsible_id))
                except (ValueError, AttributeError):
                    continue
                ids.add(uid)
                by_project.setdefault(t.project_id, set()).add(uid)
        if academy_mode_enabled():
            ids = set()
            for project_id, members in by_project.items():
                ids.update(await filter_users_to_project(self.session, project_id, list(members)))
        if not ids:
            return {}

        from app.modules.users.models import User

        rows = (await self.session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))).all()
        names: dict[str, str] = {}
        for uid, full_name, email in rows:
            label = (full_name or "").strip() or (email or "")
            if label:
                names[str(uid)] = label
        return names

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

        Idempotent set semantics - the incoming list overwrites whatever
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
            # JSONB ``@>`` containment: rows where bim_element_ids ⊇ [element_id].
            # The cast is what makes this containment. The column is declared
            # JSON for cross-dialect parity, and ``.contains()`` on a JSON column
            # compiles to a string LIKE rather than to ``@>``, which PostgreSQL
            # then rejects because the bound parameter is JSONB. Same treatment
            # as ``requirements/service.py::get_requirements_for_bim_element``.
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import JSONB

            stmt = stmt.where(cast(Task.bim_element_ids, JSONB).contains([element_id]))
            result = await self.session.execute(stmt)
            tasks = list(result.scalars().all())
        else:
            # SQLite (and anything else) - filter in Python. The query is
            # project-scoped when possible so we don't pull the entire table.
            result = await self.session.execute(stmt)
            all_tasks = list(result.scalars().all())
            tasks = [t for t in all_tasks if t.bim_element_ids and element_id in [str(x) for x in t.bim_element_ids]]

        # Respect private task visibility
        if current_user_id is not None:
            tasks = [t for t in tasks if not t.is_private or (t.created_by == current_user_id)]
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

    async def _contact_assignee(self, contact_id: uuid.UUID, actor_id: str | None) -> dict[str, Any]:
        """The fields a contact pick writes on a task.

        A contact linked to a platform user makes that user the task's
        ``responsible_id``, so my-tasks and the assignment notification follow
        it. Any other contact is not a user: ``responsible_id`` is cleared and
        the contact is kept by name and id in the metadata.

        Raises:
            HTTPException 404 for a missing or foreign contact, 422 for a
            deactivated one.
        """
        from app.modules.contacts.lookup import assignable_contact, contact_display_name

        contact = await assignable_contact(self.session, contact_id, actor_id)
        return {
            "responsible_id": str(contact.user_id) if contact.user_id else None,
            "assignee_contact_id": str(contact.id),
            "assignee_name": contact_display_name(contact),
        }

    async def update_task(
        self,
        task_id: uuid.UUID,
        data: TaskUpdate,
        current_user_id: str | None = None,
    ) -> Task:
        task = await self.get_task(task_id, current_user_id=current_user_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        # A contact pick decides the user link and the name together, so it is
        # folded into ``responsible_id`` and the metadata patch before either
        # is written. An explicit null only drops the contact link.
        if "assignee_contact_id" in fields:
            contact_id = fields.pop("assignee_contact_id")
            if contact_id is None:
                contact_fields: dict[str, Any] = {"assignee_contact_id": None}
            else:
                contact_fields = await self._contact_assignee(contact_id, current_user_id)
                fields["responsible_id"] = contact_fields.pop("responsible_id")
            incoming = fields.get("metadata")
            fields["metadata"] = {**(incoming if isinstance(incoming, dict) else {}), **contact_fields}

        # A completed task is read-only EXCEPT for a valid reopening status
        # transition (completed → open / in_progress, per _TASK_STATUS_TRANSITIONS).
        # The transition itself is validated below at the FSM check; here we only
        # ensure the request is a status-change reopening and nothing else, so a
        # completed task can be reworked but not silently edited in place.
        if task.status == "completed":
            requested_status = fields.get("status")
            is_reopen = requested_status is not None and requested_status != task.status
            if not is_reopen:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot edit a completed task",
                )
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(task, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )
        if "checklist" in fields and fields["checklist"] is not None:
            fields["checklist"] = [
                entry.model_dump() if hasattr(entry, "model_dump") else entry for entry in fields["checklist"]
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

        # Academy mode: a person the edit newly names must be in the project.
        # Names already on the task are not re-checked, so an unrelated edit
        # still saves. A no-op on a normal install.
        newly_named: list[Any] = []
        if fields.get("responsible_id") and str(fields["responsible_id"]) != str(task.responsible_id or ""):
            newly_named.append(fields["responsible_id"])
        if fields.get("persons_involved"):
            already = {str(p) for p in (task.persons_involved or [])}
            newly_named.extend(p for p in fields["persons_involved"] if str(p) not in already)
        await assert_users_can_access_project(self.session, task.project_id, newly_named)

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
        if new_responsible is not None and str(new_responsible) != old_responsible:
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

        await _safe_audit(
            self.session,
            action="update",
            entity_type="task",
            entity_id=str(task_id),
            user_id=current_user_id,
            details={
                "title": task.title[:100],
                "updated_fields": list(fields.keys()),
                "completed": True,
            },
        )

        # Completion is a status change - keep the vector index and any
        # other subscribers in sync, exactly like update_task does. Without
        # this the task stays indexed with its pre-completion status.
        await _safe_publish(
            "tasks.task.updated",
            {
                "task_id": str(task_id),
                "project_id": str(task.project_id),
                "updated_fields": list(fields.keys()),
            },
            source_module="oe_tasks",
        )
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

        Counts (total/by_status/by_type/by_priority/overdue/completed)
        come from SQL aggregates so the table never gets fully hydrated.
        Average checklist progress still needs a Python pass over the
        JSON column because portable JSON-array math isn't free in
        SQLite + PostgreSQL - but we project only `(status, checklist)`
        for that pass.
        """
        from datetime import UTC, datetime

        from sqlalchemy import func, or_, select

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")

        def _scoped(stmt):
            stmt = stmt.where(Task.project_id == project_id)
            if current_user_id is not None:
                stmt = stmt.where(
                    or_(
                        Task.is_private == False,  # noqa: E712
                        Task.created_by == current_user_id,
                    )
                )
            else:
                stmt = stmt.where(Task.is_private == False)  # noqa: E712
            return stmt

        total = (await self.session.execute(_scoped(select(func.count(Task.id))))).scalar_one()

        status_rows = (
            await self.session.execute(_scoped(select(Task.status, func.count())).group_by(Task.status))
        ).all()
        type_rows = (
            await self.session.execute(_scoped(select(Task.task_type, func.count())).group_by(Task.task_type))
        ).all()
        priority_rows = (
            await self.session.execute(_scoped(select(Task.priority, func.count())).group_by(Task.priority))
        ).all()

        by_status: dict[str, int] = {r[0]: r[1] for r in status_rows}
        by_type: dict[str, int] = {r[0]: r[1] for r in type_rows}
        by_priority: dict[str, int] = {r[0]: r[1] for r in priority_rows}

        completed_count = by_status.get("completed", 0)

        overdue_count = (
            await self.session.execute(
                _scoped(select(func.count(Task.id)))
                .where(Task.status != "completed")
                .where(Task.due_date.isnot(None))
                .where(Task.due_date < today_str)
            )
        ).scalar_one()

        # Walk only the JSON column for non-completed tasks to compute
        # average checklist progress.
        checklist_rows = (
            await self.session.execute(_scoped(select(Task.checklist)).where(Task.status != "completed"))
        ).all()

        checklist_progress_values: list[float] = []
        for (checklist,) in checklist_rows:
            if not checklist:
                continue
            total_items = len(checklist)
            if total_items == 0:
                continue
            done = sum(1 for c in checklist if isinstance(c, dict) and c.get("completed"))
            checklist_progress_values.append(done / total_items * 100)

        avg_checklist_progress: float | None = None
        if checklist_progress_values:
            avg_checklist_progress = round(sum(checklist_progress_values) / len(checklist_progress_values), 1)

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
            responsible_id: Optional - filter to a specific assignee.
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
