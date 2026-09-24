# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``rfi.create`` - the assistant drafts a request for information, a person raises it.

Mirrors ``POST /api/v1/rfi/``: permission ``rfi.create`` and
``verify_project_access`` for the person applying, then
``RFIService.create_rfi`` with that person as ``raised_by`` and creator. The
route writes nothing beside the service call, so neither does apply. The RFI
is created as a draft, like one made on the RFI page, which sends no status.

The addressee is a project member, resolved from a name like a task's
assignee (``_members``); the service puts the ball in their court and notifies
them. The cost and schedule impact are yes/no flags, and the amount or the
days are asked for only while their flag is on, as on the RFI page.

Undo deletes the RFI under the delete route's gates (``rfi.delete``), only
while it is unanswered and still holds what was applied. RFI numbers are the
project's highest number plus one, so the number of an undone RFI is handed
out again when no newer RFI exists; the card says so, and that a notification
already sent stays sent, before the person confirms.
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
    flag_option,
    make_field,
    parse_date,
    parse_decimal,
    parse_enum,
    parse_flag,
    parse_text,
    parse_whole,
    same_value,
    to_number,
)

if TYPE_CHECKING:
    from app.modules.erp_chat.models import ChatAction

PRIORITIES: tuple[str, ...] = tuple(labels.OPTIONS["rfi_priority"])
DISCIPLINES: tuple[str, ...] = tuple(labels.OPTIONS["rfi_discipline"])
# An RFI can be undone only while nobody has answered it.
_UNANSWERED: frozenset[str] = frozenset({"draft", "open"})

# What "unchanged since apply" compares before undo deletes the RFI.
_TRACKED: tuple[str, ...] = (
    "subject",
    "question",
    "status",
    "priority",
    "discipline",
    "response_due_date",
    "assigned_to",
    "cost_impact",
    "cost_impact_value",
    "schedule_impact",
    "schedule_impact_days",
    "official_response",
)


def rfi_url(rfi_id: Any) -> str:
    """The RFI's own page."""
    return f"/rfi/{rfi_id}"


class RFICreateSpec(ActionSpec):
    """Propose a new request for information in a project."""

    action_type: ClassVar[str] = "rfi.create"
    tool_name: ClassVar[str] = "propose_create_rfi"
    tool_description: ClassVar[str] = (
        "Propose a new RFI (request for information) in a project, for example 'ask the structural engineer "
        "which rebar grade applies to the level 3 slab'. Nothing is saved: the user sees a card with the RFI "
        "and applies, edits or rejects it; it is created as a draft. Use the active project unless the user "
        "names another one. Write the subject and the question in the user's language. Give the response due "
        "date as YYYY-MM-DD, working out relative dates from today's date. Name the assignee (who should answer) "
        "exactly as the user did; if no project member or several match, the RFI is proposed unassigned and the "
        "card says so. Set cost_impact or schedule_impact only when the user says the answer may change the cost "
        "or the programme."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID. Omit to use the project open in the app."},
        "subject": {"type": "string", "maxLength": 500, "description": "Short subject line."},
        "question": {"type": "string", "maxLength": 10000, "description": "The question in full."},
        "priority": {"type": "string", "enum": list(PRIORITIES), "description": "Defaults to 'normal'."},
        "discipline": {
            "type": "string",
            "enum": list(DISCIPLINES),
            "description": "The discipline the question belongs to, optional.",
        },
        "response_due_date": {"type": "string", "description": "Date the answer is needed by, YYYY-MM-DD."},
        "assignee": {
            "type": "string",
            "description": "Name or e-mail of the project member who should answer, as the user said it.",
        },
        "cost_impact": {"type": "boolean", "description": "True when the answer may change the cost."},
        "cost_impact_value": {
            "type": "number",
            "minimum": 0,
            "description": "Estimated cost exposure in the project currency, optional.",
        },
        "schedule_impact": {"type": "boolean", "description": "True when the answer may delay the schedule."},
        "schedule_impact_days": {
            "type": "integer",
            "minimum": 0,
            "description": "Working days the answer could delay the schedule, optional.",
        },
    }
    required_args: ClassVar[tuple[str, ...]] = ("subject", "question")
    entity_type: ClassVar[str] = "rfi"
    apply_permissions: ClassVar[tuple[str, ...]] = ("rfi.create",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("rfi.delete",)
    reversible: ClassVar[bool] = True
    modules: ClassVar[tuple[str, ...]] = ("oe_rfi",)
    # A picked member arrives as ``assigned_to``; an amount may come with the flag that shows its field.
    patch_aliases: ClassVar[frozenset[str]] = frozenset({"assigned_to", "cost_impact_value", "schedule_impact_days"})

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
        if "response_due_date" not in args and "due_date" in args:
            args = {**args, "response_due_date": args["due_date"]}
        errors = FieldErrors()
        subject = parse_text(args, "subject", errors, required=True, max_length=500)
        question = parse_text(args, "question", errors, required=True, max_length=10000)
        priority = parse_enum(args, "priority", errors, allowed=PRIORITIES, default="normal")
        discipline = parse_enum(args, "discipline", errors, allowed=DISCIPLINES)
        response_due_date = parse_date(args, "response_due_date", errors)
        cost_value = parse_decimal(args, "cost_impact_value", errors)
        schedule_days = parse_whole(args, "schedule_impact_days", errors)
        # A flag the model left out follows its amount; a flag set to "no" drops the amount, as the RFI page does.
        cost_impact = parse_flag(args, "cost_impact", errors, default=cost_value is not None)
        schedule_impact = parse_flag(args, "schedule_impact", errors, default=schedule_days is not None)
        members = await project_members(ctx.session, project.id)
        assignee = resolve_member(args, members, errors, key="assignee", id_key="assigned_to")
        errors.raise_if_any()
        if not cost_impact:
            cost_value = None
        if not schedule_impact:
            schedule_days = None

        payload: dict[str, Any] = {
            "project_id": str(project.id),
            "subject": subject,
            "question": question,
            "priority": priority,
            "discipline": discipline,
            "response_due_date": response_due_date,
            "assignee": assignee.shown,
            "assigned_to": str(assignee.member_id) if assignee.member_id else None,
            "cost_impact": flag_option(cost_impact),
            "cost_impact_value": decimal_str(cost_value),
            "schedule_impact": flag_option(schedule_impact),
            "schedule_impact_days": schedule_days,
        }
        fields = [
            make_field("subject", "text", subject, editable=True, required=True),
            make_field("question", "longtext", question, editable=True, required=True),
            make_field("priority", "enum", priority, editable=True, required=True, options_for="rfi_priority"),
            make_field("discipline", "enum", discipline, editable=True, options_for="rfi_discipline"),
            make_field("response_due_date", "date", response_due_date, editable=True),
            member_field("assignee", members, assignee),
            make_field("cost_impact", "enum", flag_option(cost_impact), editable=True, options_for="yes_no"),
        ]
        if cost_impact:
            fields.append(
                make_field(
                    "cost_impact_value",
                    "money",
                    to_number(cost_value),
                    currency=project.currency,
                    editable=True,
                )
            )
        fields.append(
            make_field("schedule_impact", "enum", flag_option(schedule_impact), editable=True, options_for="yes_no")
        )
        if schedule_impact:
            fields.append(make_field("schedule_impact_days", "number", schedule_days, editable=True))
        return ActionDraft(
            payload=payload,
            fields=fields,
            project_id=project.id,
            subtitle=subject,
            notes=assignee.notes,
        )

    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        ctx.require_permissions(self.apply_permissions)
        project_id = coerce_uuid(payload.get("project_id"))
        if project_id is None:
            raise ActionConflictError(code="project_not_found")
        await ctx.require_project_access(project_id)

    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        from app.modules.rfi.models import RFI
        from app.modules.rfi.schemas import RFICreate
        from app.modules.rfi.service import RFIService

        payload = draft.payload
        data = RFICreate(
            project_id=uuid.UUID(payload["project_id"]),
            subject=payload["subject"],
            question=payload["question"],
            assigned_to=payload.get("assigned_to"),
            priority=payload["priority"],
            discipline=payload.get("discipline"),
            response_due_date=payload.get("response_due_date"),
            cost_impact=payload.get("cost_impact") == "yes",
            cost_impact_value=payload.get("cost_impact_value"),
            schedule_impact=payload.get("schedule_impact") == "yes",
            schedule_impact_days=payload.get("schedule_impact_days"),
            metadata={
                "via": "ai_assistant",
                "ai_action_id": str(action.id),
                "requested_by": str(action.requested_by),
                "approved_by": str(ctx.user_id),
            },
        )
        rfi = await RFIService(ctx.session).create_rfi(data, user_id=str(ctx.user_id))
        after_state = await read_state(ctx, RFI, rfi.id, _TRACKED) or {}
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(rfi.id),
            label=f"{rfi.rfi_number} {rfi.subject}".strip(),
            url=rfi_url(rfi.id),
            after_state={**after_state, "rfi_number": rfi.rfi_number},
            audit_action="created",
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        from app.modules.rfi.models import RFI

        ctx.require_permissions(self.revert_permissions)
        rfi_id = coerce_uuid(action.applied_entity_id)
        project_id = None
        if rfi_id is not None:
            project_id = (
                await ctx.session.execute(select(RFI.project_id).where(RFI.id == rfi_id))
            ).scalar_one_or_none()
        if project_id is None:
            raise ActionConflictError(code="target_missing")
        await ctx.require_project_access(project_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        from app.modules.rfi.models import RFI
        from app.modules.rfi.service import RFIService

        rfi_id = coerce_uuid(action.applied_entity_id)
        current = await read_state(ctx, RFI, rfi_id, _TRACKED)
        if rfi_id is None or current is None:
            raise ActionConflictError(code="target_missing")
        applied_state = (action.result or {}).get("after_state") or {}
        answered = current.get("status") not in _UNANSWERED or current.get("official_response")
        if answered or any(not same_value(current[key], applied_state.get(key)) for key in _TRACKED):
            raise ActionConflictError(code="changed_since_apply")
        await RFIService(ctx.session).delete_rfi(rfi_id, actor_id=str(ctx.user_id))
        return None

    def revert_hint_key(self, action: ChatAction) -> str | None:
        applied_state = (action.result or {}).get("after_state") or {}
        hint = "rfi_notifications" if applied_state.get("assigned_to") else "rfi_number"
        return f"{labels.REVERT_HINT_PREFIX}{hint}"
