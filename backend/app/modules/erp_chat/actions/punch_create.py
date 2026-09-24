# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``punch.create_item`` - the assistant drafts a punch item, a person adds it to the list.

Mirrors ``POST /api/v1/punchlist/items/``: permission ``punchlist.create`` and
``verify_project_access`` for the person applying, then
``PunchListService.create_item`` with that person as the creator. The route
writes nothing beside the service call, so neither does apply. The service
opens every new item as ``open``.

The fields are the punch list's own: its four priorities and its categories.
A punch item has no free-text location (a location is a pin on a drawing or a
map), so the model is told to put where the defect is into the description.
The assignee is a project member resolved from a name like a task's assignee
(``_members``) and stored as the member's id, as the punch screen's own picker
does. A rework cost is taken in the currency the service will store it in:
the project's, else USD.

Undo deletes the item under the delete route's gates (``punchlist.delete``),
only while it is still open and holds what was applied. Creating an item sends
nobody a notification, so there is nothing undo cannot take back.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import select

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions._common import read_state, resolve_project
from app.modules.erp_chat.actions._members import member_field, merge_member_patch, project_members, resolve_member
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionContext,
    ActionDraft,
    ActionSpec,
    AppliedResult,
    FieldErrors,
    coerce_uuid,
    decimal_str,
    make_field,
    parse_date,
    parse_decimal,
    parse_enum,
    parse_text,
    same_value,
    to_number,
)

if TYPE_CHECKING:
    from app.modules.erp_chat.models import ChatAction

PRIORITIES: tuple[str, ...] = tuple(labels.OPTIONS["punch_priority"])
CATEGORIES: tuple[str, ...] = tuple(labels.OPTIONS["punch_category"])
# The currency ``PunchListService`` stores a rework cost in when the project has none.
FALLBACK_CURRENCY = "USD"

# What "unchanged since apply" compares before undo deletes the item.
_TRACKED: tuple[str, ...] = (
    "title",
    "description",
    "priority",
    "status",
    "assigned_to",
    "due_date",
    "category",
    "trade",
    "rework_cost",
    "resolution_notes",
)


def punch_url(item_id: Any) -> str:
    """The punch list, scrolled to and flashing this item."""
    return f"/punchlist?highlight={item_id}"


class PunchCreateItemSpec(ActionSpec):
    """Propose a new punch list item in a project."""

    action_type: ClassVar[str] = "punch.create_item"
    tool_name: ClassVar[str] = "propose_create_punch_item"
    tool_description: ClassVar[str] = (
        "Propose a new punch list item (a defect or snag to fix before handover), for example 'cracked tile in "
        "bathroom 2.04, tiler, by Friday'. Nothing is saved: the user sees a card with the item and applies, "
        "edits or rejects it; it is created as open. Use the active project unless the user names another one. "
        "Write the title and description in the user's language, and put where the defect is (room, level, "
        "grid line) into the description: a punch item has no separate location text. Give the due date as "
        "YYYY-MM-DD, working out relative dates from today's date. Name the assignee exactly as the user did; if "
        "no project member or several match, the item is proposed unassigned and the card says so."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID. Omit to use the project open in the app."},
        "title": {"type": "string", "maxLength": 255, "description": "Short title of the defect."},
        "description": {
            "type": "string",
            "maxLength": 5000,
            "description": "What is wrong and where it is (room, level, grid line).",
        },
        "priority": {"type": "string", "enum": list(PRIORITIES), "description": "Defaults to 'medium'."},
        "category": {"type": "string", "enum": list(CATEGORIES), "description": "Kind of defect, optional."},
        "trade": {"type": "string", "maxLength": 100, "description": "Trade that should fix it, optional."},
        "due_date": {"type": "string", "description": "Due date, YYYY-MM-DD."},
        "assignee": {
            "type": "string",
            "description": "Name or e-mail of the project member who should fix it, as the user said it.",
        },
        "rework_cost": {
            "type": "number",
            "minimum": 0,
            "description": "Estimated cost of the fix in the project currency, optional.",
        },
    }
    required_args: ClassVar[tuple[str, ...]] = ("title",)
    entity_type: ClassVar[str] = "punch_item"
    apply_permissions: ClassVar[tuple[str, ...]] = ("punchlist.create",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("punchlist.delete",)
    reversible: ClassVar[bool] = True
    modules: ClassVar[tuple[str, ...]] = ("oe_punchlist",)
    # A picked member arrives as ``assigned_to``.
    patch_aliases: ClassVar[frozenset[str]] = frozenset({"assigned_to"})

    def merge_patch(self, payload: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """A new assignee name is resolved again; a picked member id is taken as given."""
        return merge_member_patch(payload, patch, key="assignee", id_key="assigned_to")

    async def build(
        self,
        ctx: ActionContext,
        args: dict[str, Any],
        *,
        prior: ChatAction | None = None,
    ) -> ActionDraft:
        project = await resolve_project(ctx, args)
        errors = FieldErrors()
        title = parse_text(args, "title", errors, required=True, max_length=255)
        description = parse_text(args, "description", errors, max_length=5000)
        priority = parse_enum(args, "priority", errors, allowed=PRIORITIES, default="medium")
        category = parse_enum(args, "category", errors, allowed=CATEGORIES)
        trade = parse_text(args, "trade", errors, max_length=100)
        due_date = parse_date(args, "due_date", errors)
        rework_cost = parse_decimal(args, "rework_cost", errors)
        members = await project_members(ctx.session, project.id)
        assignee = resolve_member(args, members, errors, key="assignee", id_key="assigned_to")
        errors.raise_if_any()

        payload: dict[str, Any] = {
            "project_id": str(project.id),
            "title": title,
            "description": description,
            "priority": priority,
            "category": category,
            "trade": trade,
            "due_date": due_date,
            "assignee": assignee.shown,
            "assigned_to": str(assignee.member_id) if assignee.member_id else None,
            "rework_cost": decimal_str(rework_cost),
        }
        fields = [
            make_field("title", "text", title, editable=True, required=True),
            make_field("description", "longtext", description, editable=True),
            make_field("priority", "enum", priority, editable=True, required=True, options_for="punch_priority"),
            make_field("category", "enum", category, editable=True, options_for="punch_category"),
            make_field("trade", "text", trade, editable=True),
            make_field("due_date", "date", due_date, editable=True),
            member_field("assignee", members, assignee),
            make_field(
                "rework_cost",
                "money",
                to_number(rework_cost),
                currency=project.currency or FALLBACK_CURRENCY,
                editable=True,
            ),
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
        from app.modules.punchlist.models import PunchItem
        from app.modules.punchlist.schemas import PunchItemCreate
        from app.modules.punchlist.service import PunchListService

        payload = draft.payload
        # ``rework_cost_currency`` is left out on purpose: the service then takes the project's currency,
        # which is the one the card showed.
        data = PunchItemCreate(
            project_id=uuid.UUID(payload["project_id"]),
            title=payload["title"],
            description=payload.get("description") or "",
            priority=payload["priority"],
            category=payload.get("category"),
            trade=payload.get("trade"),
            # The date as the punch list's own form sends it (``YYYY-MM-DD``).
            due_date=payload.get("due_date"),
            assigned_to=payload.get("assigned_to"),
            rework_cost=payload.get("rework_cost"),
            metadata={
                "via": "ai_assistant",
                "ai_action_id": str(action.id),
                "requested_by": str(action.requested_by),
                "approved_by": str(ctx.user_id),
            },
        )
        item = await PunchListService(ctx.session).create_item(data, user_id=str(ctx.user_id))
        after_state = await read_state(ctx, PunchItem, item.id, _TRACKED) or {}
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(item.id),
            label=item.title,
            url=punch_url(item.id),
            after_state=after_state,
            audit_action="created",
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        from app.modules.punchlist.models import PunchItem

        ctx.require_permissions(self.revert_permissions)
        item_id = coerce_uuid(action.applied_entity_id)
        project_id = None
        if item_id is not None:
            project_id = (
                await ctx.session.execute(select(PunchItem.project_id).where(PunchItem.id == item_id))
            ).scalar_one_or_none()
        if project_id is None:
            raise ActionConflictError(code="target_missing")
        await ctx.require_project_access(project_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        from app.modules.punchlist.models import PunchItem
        from app.modules.punchlist.service import PunchListService

        item_id = coerce_uuid(action.applied_entity_id)
        current = await read_state(ctx, PunchItem, item_id, _TRACKED)
        if item_id is None or current is None:
            raise ActionConflictError(code="target_missing")
        applied_state = (action.result or {}).get("after_state") or {}
        moved_on = current.get("status") != "open"
        if moved_on or any(not same_value(current[key], applied_state.get(key)) for key in _TRACKED):
            raise ActionConflictError(code="changed_since_apply")
        await PunchListService(ctx.session).delete_item(item_id)
        return None
