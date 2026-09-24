# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``risk.create`` - the assistant drafts a risk, a person logs it in the register.

Mirrors ``POST /api/v1/risk/``: permission ``risk.create`` for the person
applying, then ``RiskService.create_risk`` with that person as the actor. The
route runs no project check, so any project id would do; apply checks
``verify_project_access`` anyway, as every other create route does, so the
assistant never becomes a way into a project the person cannot open. The route
writes nothing beside the service call, so neither does apply.

The fields are the register's own: its categories and its five-level impact
scale; the probability is shown in percent and stored as the 0..1 fraction the
register keeps. The owner is a project member resolved from a name like a
task's assignee (``_members``); the service notifies them. A risk whose
probability and impact cross the escalation threshold is escalated by the
service as soon as it is logged.

Undo deletes the risk under the delete route's gates (``risk.delete``), only
while it still holds what was applied. Risk codes are the project's risk count
plus one, so the code of an undone risk is handed out again; the card says so,
and that an owner notification or an escalation notice already sent stays
sent, before the person confirms.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import select

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions._common import load_project, read_state, resolve_project
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
    parse_decimal,
    parse_enum,
    parse_percent,
    parse_text,
    parse_whole,
    same_value,
    to_number,
)

if TYPE_CHECKING:
    from app.modules.erp_chat.models import ChatAction

CATEGORIES: tuple[str, ...] = tuple(labels.OPTIONS["risk_category"])
IMPACTS: tuple[str, ...] = tuple(labels.OPTIONS["risk_impact"])
# The register's defaults for a new risk (``RiskCreate``): a coin toss, medium impact.
DEFAULT_PROBABILITY = Decimal("50")

# What "unchanged since apply" compares before undo deletes the risk. ``escalated`` is in it
# so a risk the escalation sweep picked up later counts as moved on.
_TRACKED: tuple[str, ...] = (
    "code",
    "title",
    "description",
    "category",
    "probability",
    "impact_severity",
    "impact_cost",
    "impact_schedule_days",
    "status",
    "mitigation_strategy",
    "owner_user_id",
    "owner_name",
    "escalated",
)


def risk_url(risk_id: Any) -> str:
    """The risk register, opened on this risk."""
    return f"/risks?id={risk_id}"


class RiskCreateSpec(ActionSpec):
    """Propose a new risk in a project's risk register."""

    action_type: ClassVar[str] = "risk.create"
    tool_name: ClassVar[str] = "propose_create_risk"
    tool_description: ClassVar[str] = (
        "Propose a new risk for a project's risk register, for example 'risk that the crane permit is late, "
        "likely, high impact, about 20 days delay'. Nothing is saved: the user sees a card with the risk and "
        "applies, edits or rejects it. Use the active project unless the user names another one. Write the "
        "title, description and mitigation in the user's language. Give probability in percent (0-100) and the "
        "cost in the project currency. Name the owner exactly as the user did; if no project member or several "
        "match, the risk is proposed without an owner and the card says so."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID. Omit to use the project open in the app."},
        "title": {"type": "string", "maxLength": 255, "description": "Short name of the risk."},
        "description": {"type": "string", "maxLength": 5000, "description": "What could happen and why, optional."},
        "category": {"type": "string", "enum": list(CATEGORIES), "description": "Defaults to 'technical'."},
        "probability": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "description": "Likelihood in percent, e.g. 70. Defaults to 50.",
        },
        "impact_severity": {
            "type": "string",
            "enum": list(IMPACTS),
            "description": "How bad it is if it happens. Defaults to 'medium'.",
        },
        "impact_cost": {
            "type": "number",
            "minimum": 0,
            "description": "Cost if it happens, in the project currency, optional.",
        },
        "impact_schedule_days": {
            "type": "integer",
            "minimum": 0,
            "description": "Delay in days if it happens, optional.",
        },
        "owner": {
            "type": "string",
            "description": "Name or e-mail of the project member who owns the risk, as the user said it.",
        },
        "mitigation_strategy": {
            "type": "string",
            "maxLength": 5000,
            "description": "How to reduce or avoid the risk, optional.",
        },
    }
    required_args: ClassVar[tuple[str, ...]] = ("title",)
    entity_type: ClassVar[str] = "risk"
    apply_permissions: ClassVar[tuple[str, ...]] = ("risk.create",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("risk.delete",)
    reversible: ClassVar[bool] = True
    modules: ClassVar[tuple[str, ...]] = ("oe_risk",)
    # A picked member arrives as ``owner_user_id``.
    patch_aliases: ClassVar[frozenset[str]] = frozenset({"owner_user_id"})

    def merge_patch(self, payload: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """A new owner name is resolved again; a picked member id is taken as given."""
        return merge_member_patch(payload, patch, key="owner", id_key="owner_user_id")

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
        category = parse_enum(args, "category", errors, allowed=CATEGORIES, default="technical")
        probability = parse_percent(args, "probability", errors)
        impact = parse_enum(args, "impact_severity", errors, allowed=IMPACTS, default="medium")
        impact_cost = parse_decimal(args, "impact_cost", errors)
        impact_days = parse_whole(args, "impact_schedule_days", errors)
        mitigation = parse_text(args, "mitigation_strategy", errors, max_length=5000)
        members = await project_members(ctx.session, project.id)
        owner = resolve_member(args, members, errors, key="owner", id_key="owner_user_id")
        errors.raise_if_any()
        if probability is None:
            probability = DEFAULT_PROBABILITY

        payload: dict[str, Any] = {
            "project_id": str(project.id),
            "title": title,
            "description": description,
            "category": category,
            "probability": decimal_str(probability),
            "impact_severity": impact,
            "impact_cost": decimal_str(impact_cost),
            "impact_schedule_days": impact_days,
            "owner": owner.shown,
            "owner_user_id": str(owner.member_id) if owner.member_id else None,
            "mitigation_strategy": mitigation,
        }
        fields = [
            make_field("title", "text", title, editable=True, required=True),
            make_field("description", "longtext", description, editable=True),
            make_field("category", "enum", category, editable=True, required=True, options_for="risk_category"),
            make_field("probability", "percent", to_number(probability), editable=True, required=True),
            make_field(
                "impact_severity",
                "enum",
                impact,
                editable=True,
                required=True,
                options_for="risk_impact",
            ),
            make_field("impact_cost", "money", to_number(impact_cost), currency=project.currency, editable=True),
            make_field("impact_schedule_days", "number", impact_days, editable=True),
            member_field("owner", members, owner),
            make_field("mitigation_strategy", "longtext", mitigation, editable=True),
        ]
        return ActionDraft(
            payload=payload,
            fields=fields,
            project_id=project.id,
            subtitle=title,
            notes=owner.notes,
        )

    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        # ``POST /risk/`` checks only the permission; the project check is added here on purpose.
        ctx.require_permissions(self.apply_permissions)
        project_id = coerce_uuid(payload.get("project_id"))
        if project_id is None:
            raise ActionConflictError(code="project_not_found")
        await ctx.require_project_access(project_id)

    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        from app.modules.risk.models import RiskItem
        from app.modules.risk.schemas import RiskCreate
        from app.modules.risk.service import RiskService

        payload = draft.payload
        project = await load_project(ctx, uuid.UUID(payload["project_id"]))
        owner_id = coerce_uuid(payload.get("owner_user_id"))
        data = RiskCreate(
            project_id=project.id,
            title=payload["title"],
            description=payload.get("description") or "",
            category=payload["category"],
            probability=float(Decimal(payload["probability"]) / 100),
            impact_severity=payload["impact_severity"],
            impact_cost=Decimal(payload.get("impact_cost") or "0"),
            impact_schedule_days=int(payload.get("impact_schedule_days") or 0),
            mitigation_strategy=payload.get("mitigation_strategy") or "",
            owner_name=(payload.get("owner") or "") if owner_id else "",
            owner_user_id=owner_id,
            # The risk page sends the project currency; the service falls back to it as well.
            currency=project.currency,
            metadata={
                "via": "ai_assistant",
                "ai_action_id": str(action.id),
                "requested_by": str(action.requested_by),
                "approved_by": str(ctx.user_id),
            },
        )
        item = await RiskService(ctx.session).create_risk(data, user_id=str(ctx.user_id))
        after_state = await read_state(ctx, RiskItem, item.id, _TRACKED) or {}
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(item.id),
            label=f"{after_state.get('code') or item.code} {item.title}".strip(),
            url=risk_url(item.id),
            after_state=after_state,
            audit_action="created",
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        from app.modules.risk.models import RiskItem

        ctx.require_permissions(self.revert_permissions)
        risk_id = coerce_uuid(action.applied_entity_id)
        project_id = None
        if risk_id is not None:
            project_id = (
                await ctx.session.execute(select(RiskItem.project_id).where(RiskItem.id == risk_id))
            ).scalar_one_or_none()
        if project_id is None:
            raise ActionConflictError(code="target_missing")
        await ctx.require_project_access(project_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        from app.modules.risk.models import RiskItem
        from app.modules.risk.service import RiskService

        risk_id = coerce_uuid(action.applied_entity_id)
        current = await read_state(ctx, RiskItem, risk_id, _TRACKED)
        if risk_id is None or current is None:
            raise ActionConflictError(code="target_missing")
        applied_state = (action.result or {}).get("after_state") or {}
        if any(not same_value(current[key], applied_state.get(key)) for key in _TRACKED):
            raise ActionConflictError(code="changed_since_apply")
        await RiskService(ctx.session).delete_risk(risk_id)
        return None

    def revert_hint_key(self, action: ChatAction) -> str | None:
        applied_state = (action.result or {}).get("after_state") or {}
        if applied_state.get("escalated"):
            hint = "risk_escalated"
        elif applied_state.get("owner_user_id"):
            hint = "risk_notifications"
        else:
            hint = "risk_code"
        return f"{labels.REVERT_HINT_PREFIX}{hint}"
