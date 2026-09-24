# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``task.create`` - the assistant proposes a task, a person creates it.

Mirrors ``POST /api/v1/tasks/``: permission ``tasks.create`` and
``verify_project_access`` for the person applying, then
``TaskService.create_task`` with that person as the creator. The route writes
nothing beside the service call, so neither does apply.

An assignee is given by name and is resolved to a project member (the owner or
anyone on one of the project's teams) only when exactly one matches. Otherwise
the task is proposed without an assignee and a note says so, because assigning
a task to the wrong person sends that person a notification. On the card the
assignee is a list of the project's members, so the person picks one rather
than retyping a name; the pick arrives as the member's id (``_members``).

Undo deletes the task through ``TaskService.delete_task`` under the delete
route's gates (``tasks.delete``), and only while the task still holds what was
applied. A notification already sent to the assignee stays sent, and the card
says so before the person confirms the undo.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import select

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions._common import resolve_project

# ``match_members`` and ``member_options`` are re-exported: they lived here before ``_members``.
from app.modules.erp_chat.actions._members import match_members as match_members
from app.modules.erp_chat.actions._members import (
    member_field,
    merge_member_patch,
    project_members,
    resolve_member,
)
from app.modules.erp_chat.actions._members import member_options as member_options
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionContext,
    ActionDraft,
    ActionSpec,
    AppliedResult,
    FieldErrors,
    coerce_uuid,
    make_field,
    parse_date,
    parse_enum,
    parse_text,
    same_value,
)

if TYPE_CHECKING:
    from app.modules.erp_chat.models import ChatAction

TASK_TYPES: tuple[str, ...] = tuple(labels.OPTIONS["task_type"])
PRIORITIES: tuple[str, ...] = tuple(labels.OPTIONS["priority"])

# What "unchanged since apply" compares before undo deletes the task.
_TRACKED: tuple[str, ...] = ("title", "description", "task_type", "priority", "due_date", "responsible_id")


def task_url(project_id: Any, task_id: Any) -> str:
    """Deep link the Tasks page understands (scrolls to and highlights the card)."""
    return f"/projects/{project_id}/tasks?id={task_id}"


class TaskCreateSpec(ActionSpec):
    """Propose a new task in a project."""

    action_type: ClassVar[str] = "task.create"
    tool_name: ClassVar[str] = "propose_create_task"
    tool_description: ClassVar[str] = (
        "Propose a new task in a project, for example 'check formwork on level 3 by Friday'. "
        "Nothing is saved: the user sees a card with the task and applies, edits or rejects it. "
        "Use the active project unless the user names another one. Give the due date as YYYY-MM-DD, "
        "working out relative dates ('by Friday') from today's date. Name the assignee exactly as the "
        "user did; if no project member or several match, the task is proposed unassigned and the card "
        "says so."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {
            "type": "string",
            "description": "Project UUID. Omit to use the project open in the app.",
        },
        "title": {"type": "string", "maxLength": 500, "description": "Short task title."},
        "description": {"type": "string", "maxLength": 5000, "description": "Details, optional."},
        "task_type": {
            "type": "string",
            "enum": list(TASK_TYPES),
            "description": "Kind of task; 'task' unless the user says otherwise.",
        },
        "priority": {"type": "string", "enum": list(PRIORITIES), "description": "Defaults to 'normal'."},
        "due_date": {"type": "string", "description": "Due date, YYYY-MM-DD."},
        "assignee": {
            "type": "string",
            "description": "Name or e-mail of the project member who should do it, as the user said it.",
        },
    }
    required_args: ClassVar[tuple[str, ...]] = ("title",)
    entity_type: ClassVar[str] = "task"
    apply_permissions: ClassVar[tuple[str, ...]] = ("tasks.create",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("tasks.delete",)
    reversible: ClassVar[bool] = True
    modules: ClassVar[tuple[str, ...]] = ("oe_tasks",)
    patch_aliases: ClassVar[frozenset[str]] = frozenset({"responsible_id"})

    def merge_patch(self, payload: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """A new assignee name is resolved again; a picked member id is taken as given."""
        return merge_member_patch(payload, patch, key="assignee", id_key="responsible_id")

    async def build(
        self,
        ctx: ActionContext,
        args: dict[str, Any],
        *,
        prior: ChatAction | None = None,
    ) -> ActionDraft:
        project = await resolve_project(ctx, args)
        errors = FieldErrors()
        title = parse_text(args, "title", errors, required=True, max_length=500)
        description = parse_text(args, "description", errors, max_length=5000)
        task_type = parse_enum(args, "task_type", errors, allowed=TASK_TYPES, default="task")
        priority = parse_enum(args, "priority", errors, allowed=PRIORITIES, default="normal")
        due_date = parse_date(args, "due_date", errors)
        members = await project_members(ctx.session, project.id)
        assignee = resolve_member(
            args,
            members,
            errors,
            key="assignee",
            id_key="responsible_id",
            unmatched_note="assignee_unmatched",
            ambiguous_note="assignee_ambiguous",
        )
        errors.raise_if_any()

        payload: dict[str, Any] = {
            "project_id": str(project.id),
            "title": title,
            "description": description,
            "task_type": task_type,
            "priority": priority,
            "due_date": due_date,
            "assignee": assignee.shown,
            "responsible_id": str(assignee.member_id) if assignee.member_id else None,
        }
        fields = [
            make_field("title", "text", title, editable=True, required=True),
            make_field("description", "longtext", description, editable=True),
            make_field("task_type", "enum", task_type, editable=True, required=True),
            make_field("priority", "enum", priority, editable=True, required=True),
            make_field("due_date", "date", due_date, editable=True),
            member_field("assignee", members, assignee),
        ]
        return ActionDraft(
            payload=payload,
            fields=fields,
            project_id=project.id,
            subtitle=title,
            notes=assignee.notes,
        )

    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        ctx.require_permissions(self.apply_permissions)
        project_id = coerce_uuid(payload.get("project_id"))
        if project_id is None:
            raise ActionConflictError(code="project_not_found")
        await ctx.require_project_access(project_id)

    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        from app.modules.tasks.schemas import TaskCreate
        from app.modules.tasks.service import TaskService

        payload = draft.payload
        data = TaskCreate(
            project_id=uuid.UUID(payload["project_id"]),
            task_type=payload["task_type"],
            title=payload["title"],
            description=payload.get("description"),
            due_date=payload.get("due_date"),
            priority=payload["priority"],
            responsible_id=payload.get("responsible_id"),
            metadata={
                "via": "ai_assistant",
                "ai_action_id": str(action.id),
                "requested_by": str(action.requested_by),
                "approved_by": str(ctx.user_id),
            },
        )
        task = await TaskService(ctx.session).create_task(data, user_id=str(ctx.user_id))
        after_state = _task_state(task)
        return AppliedResult(
            entity_type="task",
            entity_id=str(task.id),
            label=task.title,
            url=task_url(task.project_id, task.id),
            after_state=after_state,
            audit_action="created",
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        ctx.require_permissions(self.revert_permissions)
        project_id = coerce_uuid((action.payload or {}).get("project_id")) or action.project_id
        if project_id is None:
            raise ActionConflictError(code="project_not_found")
        await ctx.require_project_access(project_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        from app.modules.tasks.models import Task
        from app.modules.tasks.service import TaskService

        task_id = coerce_uuid(action.applied_entity_id)
        applied_state = (action.result or {}).get("after_state") or {}
        row = None
        if task_id is not None:
            columns = [getattr(Task, key) for key in _TRACKED]
            row = (await ctx.session.execute(select(*columns).where(Task.id == task_id))).one_or_none()
        if row is None:
            raise ActionConflictError(code="target_missing")
        current = {key: _state_value(value) for key, value in zip(_TRACKED, row, strict=True)}
        if any(not same_value(current[key], applied_state.get(key)) for key in _TRACKED):
            raise ActionConflictError(code="changed_since_apply")
        service = TaskService(ctx.session)
        await service.get_task(task_id, current_user_id=str(ctx.user_id))
        await service.delete_task(task_id, current_user_id=str(ctx.user_id))
        return None

    def revert_hint_key(self, action: ChatAction) -> str | None:
        applied_state = (action.result or {}).get("after_state") or {}
        if applied_state.get("responsible_id"):
            return f"{labels.REVERT_HINT_PREFIX}task_notifications"
        return None


def _state_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _task_state(task: Any) -> dict[str, Any]:
    state = {key: _state_value(getattr(task, key, None)) for key in _TRACKED}
    state["status"] = getattr(task, "status", None)
    return state
