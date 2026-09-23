# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``boq.update_position`` - the assistant proposes new values for a BOQ line.

Mirrors ``PATCH /api/v1/boq/positions/{position_id}``: permission
``boq.update``, the position must exist, and ``_verify_boq_owner`` on its bill
for the person applying; then ``BOQService.update_position`` with that person
as ``actor_id``, which writes the field-level ``BOQActivityLog`` diff itself.
The route writes nothing else, so neither does apply. Only description,
quantity, unit and unit rate can be proposed; ``source`` is never touched, so a
hand-typed line does not start to look AI-made because its quantity changed.

The values the line held when the change was proposed are kept in
``before_state``. Apply (and every edit of the proposal) compares the fields
being changed with those values and refuses with 409 ``target_changed`` when
someone changed the line in between, instead of silently overwriting their
work. Undo restores the old values, only while the line still holds what was
applied.

Linked lines (issue #127) are called out on the card: changing the
description, unit or rate of a master changes every linked line, and changing
them on a linked instance unlinks it, which undo does not reverse.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions._boq import (
    LineRow,
    get_bill,
    get_line,
    line_total,
    linked_count,
    position_state,
    position_url,
    project_bills,
    resolve_bill,
    verify_bill_access,
)
from app.modules.erp_chat.actions._common import load_project, resolve_project
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionContext,
    ActionDraft,
    ActionNotFoundError,
    ActionSpec,
    ActionValidationError,
    AppliedResult,
    FieldErrors,
    coerce_uuid,
    decimal_str,
    make_field,
    make_note,
    parse_decimal,
    parse_text,
    same_value,
    to_number,
)
from app.modules.erp_chat.schemas import ActionEntityRef, ActionField

if TYPE_CHECKING:
    from app.modules.erp_chat.models import ChatAction

# The fields a proposal may change, in the order the card shows them.
EDITABLE: tuple[str, ...] = ("description", "quantity", "unit", "unit_rate")
_NUMERIC: frozenset[str] = frozenset({"quantity", "unit_rate"})
# Changing these on a linked line propagates (master) or unlinks (instance).
_DEFINITION_FIELDS: frozenset[str] = frozenset({"description", "unit", "unit_rate"})


def _changes(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in EDITABLE if key in payload}


def _update_values(values: dict[str, Any]) -> dict[str, Any]:
    """Payload strings to the types ``PositionUpdate`` declares."""
    converted: dict[str, Any] = {}
    for key, value in values.items():
        if key == "quantity":
            converted[key] = float(Decimal(str(value)))
        elif key == "unit_rate":
            converted[key] = Decimal(str(value))
        else:
            converted[key] = value
    return converted


async def _find_by_ordinal(
    ctx: ActionContext,
    args: dict[str, Any],
    errors: FieldErrors,
) -> LineRow:
    """A line named by its number: in the given bill, else in whichever bill of the project has it."""
    from sqlalchemy import select

    from app.modules.boq.models import Position

    ordinal = parse_text(args, "ordinal", errors, required=True, max_length=50)
    if ordinal is None:
        errors.add("position_id", "required")
        errors.raise_if_any()
    project = await resolve_project(ctx, args)
    if args.get("boq_id") not in (None, "") or args.get("boq"):
        bills = [await resolve_bill(ctx, project.id, args)]
    else:
        bills = await project_bills(ctx, project.id)
    by_id = {b.id: b for b in bills}
    if not by_id:
        raise ActionValidationError(code="no_boq")
    stmt = select(Position.id, Position.boq_id).where(
        Position.boq_id.in_(list(by_id)),
        Position.ordinal == ordinal,
    )
    hits = (await ctx.session.execute(stmt)).all()
    if not hits:
        raise ActionValidationError(code="position_not_found", params={"ordinal": ordinal})
    if len(hits) > 1:
        raise ActionValidationError(
            code="position_ambiguous",
            options=[{"boq_id": str(boq_id), "name": by_id[boq_id].name} for _pid, boq_id in hits],
        )
    line = await get_line(ctx, hits[0][0])
    if line is None:  # deleted between the two reads
        raise ActionValidationError(code="position_not_found", params={"ordinal": ordinal})
    return line


class BOQUpdatePositionSpec(ActionSpec):
    """Propose new values for an existing BOQ line."""

    action_type: ClassVar[str] = "boq.update_position"
    tool_name: ClassVar[str] = "propose_update_boq_position"
    tool_description: ClassVar[str] = (
        "Propose new values for an existing line of a bill of quantities, e.g. 'set position 03.012 to "
        "120 m3'. Identify the line by position_id, or by its number (ordinal) plus boq_id when the project "
        "has several bills. Pass only the fields that change: description, quantity, unit, unit_rate. "
        "Nothing is saved: the user sees the old and new values on a card and applies, edits or rejects it."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID. Omit to use the project open in the app."},
        "position_id": {"type": "string", "description": "UUID of the line, when you have it."},
        "ordinal": {"type": "string", "description": "The line's position number, e.g. '03.012'."},
        "boq_id": {"type": "string", "description": "UUID of the bill the line is in."},
        "boq": {"type": "string", "description": "Name of the bill, when you do not have its id."},
        "description": {"type": "string", "maxLength": 5000, "description": "New description."},
        "quantity": {"type": "number", "minimum": 0, "description": "New quantity."},
        "unit": {"type": "string", "maxLength": 20, "description": "New unit of measurement."},
        "unit_rate": {"type": "number", "minimum": 0, "description": "New price per unit, project currency."},
    }
    required_args: ClassVar[tuple[str, ...]] = ()
    entity_type: ClassVar[str] = "position"
    apply_permissions: ClassVar[tuple[str, ...]] = ("boq.update",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("boq.update",)
    reversible: ClassVar[bool] = True
    modules: ClassVar[tuple[str, ...]] = ("oe_boq",)

    async def build(
        self,
        ctx: ActionContext,
        args: dict[str, Any],
        *,
        prior: ChatAction | None = None,
    ) -> ActionDraft:
        errors = FieldErrors()
        raw_id = args.get("position_id")
        if raw_id not in (None, ""):
            position_id = coerce_uuid(raw_id)
            line = await get_line(ctx, position_id) if position_id is not None else None
            if line is None:
                raise ActionValidationError(code="position_not_found")
        else:
            line = await _find_by_ordinal(ctx, args, errors)
        bill = await get_bill(ctx, line.boq_id)
        if bill is None:
            raise ActionValidationError(code="position_not_found")
        try:
            await ctx.require_project_access(bill.project_id)
        except ActionNotFoundError as exc:
            raise ActionNotFoundError(code="position_not_found") from exc
        if line.is_section:
            raise ActionValidationError(code="position_is_section")
        if bill.is_locked:
            raise ActionConflictError(code="locked", params={"boq": bill.name})

        requested: dict[str, Any] = {}
        for key in EDITABLE:
            if key not in args or args.get(key) is None:
                continue
            if key in _NUMERIC:
                number = parse_decimal(args, key, errors, required=True)
                if number is not None:
                    requested[key] = decimal_str(number)
            else:
                limit = 5000 if key == "description" else 20
                text = parse_text(args, key, errors, required=key == "unit", max_length=limit)
                if text is not None:
                    requested[key] = text
        errors.raise_if_any()

        current = line.state()
        if prior is not None and prior.before_state:
            before = dict(prior.before_state)
            drifted = [key for key in requested if not same_value(current.get(key), before.get(key))]
            if drifted:
                raise ActionConflictError(code="target_changed", params={"fields": drifted})
        else:
            before = {**current, "link_role": line.link_role, "linked_count": await linked_count(ctx, line)}

        changes = {key: value for key, value in requested.items() if not same_value(value, before.get(key))}
        if not changes:
            raise ActionValidationError(code="no_change")

        project = await load_project(ctx, bill.project_id)
        currency = project.currency or None
        new_state = {**before, **changes}
        fields: list[ActionField] = []
        for key in EDITABLE:
            if key not in changes:
                continue
            if key == "description":
                fields.append(
                    make_field(key, "longtext", changes[key], before=before.get(key), editable=True, required=True)
                )
            elif key == "quantity":
                fields.append(
                    make_field(
                        key,
                        "number",
                        to_number(changes[key]),
                        before=to_number(before.get(key)),
                        unit=new_state.get("unit"),
                        editable=True,
                        required=True,
                    )
                )
            elif key == "unit":
                fields.append(
                    make_field(key, "text", changes[key], before=before.get(key), editable=True, required=True)
                )
            else:
                fields.append(
                    make_field(
                        key,
                        "money",
                        to_number(changes[key]),
                        before=to_number(before.get(key)),
                        currency=currency,
                        editable=True,
                        required=True,
                    )
                )
        if {"quantity", "unit_rate"} & set(changes):
            fields.append(
                make_field(
                    "total",
                    "money",
                    to_number(line_total(new_state.get("quantity"), new_state.get("unit_rate"))),
                    before=to_number(line_total(before.get("quantity"), before.get("unit_rate"))),
                    currency=currency,
                )
            )

        notes = []
        touches_definition = bool(_DEFINITION_FIELDS & set(changes))
        link_role = before.get("link_role")
        if touches_definition and link_role == "master" and int(before.get("linked_count") or 0) > 0:
            notes.append(make_note("linked_master", params={"count": int(before["linked_count"])}, tone="warning"))
        elif touches_definition and link_role == "instance":
            notes.append(make_note("linked_instance", tone="warning"))

        payload = {
            "project_id": str(bill.project_id),
            "boq_id": str(bill.id),
            "position_id": str(line.id),
            **changes,
        }
        target_label = f"{before.get('ordinal') or line.ordinal} {str(before.get('description') or '')[:60]}"
        return ActionDraft(
            payload=payload,
            fields=fields,
            project_id=bill.project_id,
            subtitle=bill.name,
            target=ActionEntityRef(
                entity_type=self.entity_type,
                entity_id=str(line.id),
                label=target_label.strip(),
                url=position_url(bill.id, line.id),
            ),
            before_state=before,
            notes=notes,
        )

    async def _gate_line(self, ctx: ActionContext, position_id: uuid.UUID | None) -> LineRow:
        line = await get_line(ctx, position_id) if position_id is not None else None
        if line is None:
            raise ActionNotFoundError(code="position_not_found")
        await verify_bill_access(ctx, line.boq_id)
        return line

    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        ctx.require_permissions(self.apply_permissions)
        await self._gate_line(ctx, coerce_uuid(payload.get("position_id")))

    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        from app.modules.boq.schemas import PositionUpdate
        from app.modules.boq.service import BOQService

        position_id = uuid.UUID(draft.payload["position_id"])
        changes = _changes(draft.payload)
        position = await BOQService(ctx.session).update_position(
            position_id,
            PositionUpdate(**_update_values(changes)),
            actor_id=ctx.user_id,
        )
        after_state = position_state(position)
        before_state = {key: value for key, value in (draft.before_state or {}).items() if key in after_state}
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(position.id),
            label=f"{position.ordinal} {(position.description or '')[:60]}".strip(),
            url=position_url(position.boq_id, position.id),
            after_state=after_state,
            audit_action="updated",
            before_state=before_state,
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        ctx.require_permissions(self.revert_permissions)
        position_id = coerce_uuid(action.applied_entity_id)
        line = await get_line(ctx, position_id) if position_id is not None else None
        if line is None:
            raise ActionConflictError(code="target_missing")
        await verify_bill_access(ctx, line.boq_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        from app.modules.boq.schemas import PositionUpdate
        from app.modules.boq.service import BOQService

        position_id = coerce_uuid(action.applied_entity_id)
        line = await get_line(ctx, position_id) if position_id is not None else None
        if line is None:
            raise ActionConflictError(code="target_missing")
        changed = list(_changes(action.payload or {}))
        applied_state = (action.result or {}).get("after_state") or {}
        current = line.state()
        if any(not same_value(current.get(key), applied_state.get(key)) for key in changed):
            raise ActionConflictError(code="changed_since_apply")
        bill = await get_bill(ctx, line.boq_id)
        if bill is not None and bill.is_locked:
            raise ActionConflictError(code="locked", params={"boq": bill.name})
        before = action.before_state or {}
        restore = {key: before[key] for key in changed if key in before}
        position = await BOQService(ctx.session).update_position(
            line.id,
            PositionUpdate(**_update_values(restore)),
            actor_id=ctx.user_id,
        )
        return position_state(position)

    def revert_hint_key(self, action: ChatAction) -> str | None:
        before = action.before_state or {}
        if before.get("link_role") == "instance" and _DEFINITION_FIELDS & set(_changes(action.payload or {})):
            return f"{labels.REVERT_HINT_PREFIX}position_unlinked"
        return None
