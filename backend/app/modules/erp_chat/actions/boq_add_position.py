# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``boq.add_position`` - the assistant proposes a BOQ line, a person adds it.

Mirrors ``POST /api/v1/boq/boqs/{boq_id}/positions/``: permission
``boq.update`` and ``_verify_boq_owner`` for the person applying, then
``BOQService.add_position``, then the ``position_added`` activity row the route
writes beside the service call, with that person as the actor.

The line goes where the editor's "Add position" puts it when nothing is
selected: into the bill's last section, numbered like the editor numbers it.
It carries ``source="ai_match"`` and the proposal's confidence, so the grid's
AI filter finds it and its number shows the confidence chip, and its metadata
names the action and the people involved. A locked bill is refused (409
``locked``) at proposal and again at apply.

Undo deletes the line under the delete route's gates (``boq.delete``), only
while the line still holds exactly what was applied and the bill is not locked.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from app.modules.erp_chat.actions._boq import (
    AI_SOURCE,
    LineRow,
    bill_lines,
    get_bill,
    get_line,
    line_total,
    next_ordinal,
    position_state,
    position_url,
    resolve_bill,
    verify_bill_access,
)
from app.modules.erp_chat.actions._common import pending_payloads, resolve_project
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

if TYPE_CHECKING:
    from app.modules.boq.service import BOQService
    from app.modules.erp_chat.models import ChatAction

logger = logging.getLogger(__name__)

# What "unchanged since apply" compares before undo deletes the line.
_TRACKED: tuple[str, ...] = ("ordinal", "description", "unit", "quantity", "unit_rate")


def _section_options(sections: list[LineRow]) -> list[dict[str, Any]]:
    return [{"id": str(s.id), "ordinal": s.ordinal, "name": s.description} for s in sections]


def _resolve_section(lines: list[LineRow], args: dict[str, Any]) -> tuple[LineRow | None, bool]:
    """The section the new line goes under, and whether the bill has none at all.

    ``section_id`` (a stored payload) is taken as given, None meaning top
    level. ``section`` (the model's words) matches a section number exactly,
    else a unique part of a section name. With neither, the last top-level
    section, as the editor does.
    """
    sections = [line for line in lines if line.is_section]
    if "section_id" in args:
        raw = args.get("section_id")
        if raw in (None, ""):
            return None, not sections
        wanted_id = coerce_uuid(raw)
        match = next((s for s in sections if s.id == wanted_id), None)
        if match is None:
            raise ActionValidationError(code="section_not_found", options=_section_options(sections))
        return match, False
    wanted = str(args.get("section") or "").strip()
    if wanted:
        exact = [s for s in sections if s.ordinal.strip() == wanted]
        if len(exact) == 1:
            return exact[0], False
        folded = wanted.casefold()
        named = exact or [s for s in sections if folded in s.description.casefold()]
        if len(named) == 1:
            return named[0], False
        code = "section_ambiguous" if named else "section_not_found"
        raise ActionValidationError(code=code, options=_section_options(named or sections))
    top_level = [s for s in sections if s.parent_id is None] or sections
    if not top_level:
        return None, True
    return max(top_level, key=lambda s: (s.sort_order, s.ordinal)), False


async def _write_route_activity(
    service: BOQService,
    *,
    user_id: uuid.UUID,
    action: str,
    description: str,
    project_id: uuid.UUID | None,
    boq_id: uuid.UUID,
    target_id: uuid.UUID,
    metadata: dict[str, Any],
) -> None:
    """The ``BOQActivityLog`` row the BOQ route writes itself, never failing the write.

    In its own savepoint: a failed flush here must not poison the transaction
    the position was written in.
    """
    try:
        async with service.session.begin_nested():
            await service.log_activity(
                user_id=user_id,
                action=action,
                target_type="position",
                description=description,
                project_id=project_id,
                boq_id=boq_id,
                target_id=target_id,
                metadata_=metadata,
            )
    except Exception:
        logger.warning("BOQ activity row for %s %s was not written", action, target_id, exc_info=True)


class BOQAddPositionSpec(ActionSpec):
    """Propose a new priced line in a bill of quantities."""

    action_type: ClassVar[str] = "boq.add_position"
    tool_name: ClassVar[str] = "propose_add_boq_position"
    tool_description: ClassVar[str] = (
        "Propose a new line (position) in a bill of quantities, e.g. '120 m3 of C30/37 concrete for the "
        "level 3 slab at 145 per m3'. Nothing is saved: the user sees a card and applies, edits or rejects "
        "it. Rates are in the project currency. If the project has several bills and the user did not say "
        "which one, the tool returns the list: ask the user, then call again with boq_id. The line goes "
        "into the bill's last section and is numbered automatically unless you pass section or ordinal."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID. Omit to use the project open in the app."},
        "boq_id": {"type": "string", "description": "UUID of the bill of quantities."},
        "boq": {"type": "string", "description": "Name of the bill, when you do not have its id."},
        "section": {
            "type": "string",
            "description": "Number (e.g. '03') or name of the section to put the line in. Omit for the last one.",
        },
        "description": {"type": "string", "maxLength": 5000, "description": "What the line is for."},
        "unit": {"type": "string", "maxLength": 20, "description": "Unit of measurement, e.g. m3, m2, m, kg, pcs."},
        "quantity": {"type": "number", "minimum": 0, "description": "Quantity in that unit."},
        "unit_rate": {
            "type": "number",
            "minimum": 0,
            "description": "Price per unit in the project currency. Omit when unknown (the line is added unpriced).",
        },
        "ordinal": {"type": "string", "description": "Position number. Omit to number it automatically."},
    }
    required_args: ClassVar[tuple[str, ...]] = ("description", "unit", "quantity")
    entity_type: ClassVar[str] = "position"
    apply_permissions: ClassVar[tuple[str, ...]] = ("boq.update",)
    revert_permissions: ClassVar[tuple[str, ...]] = ("boq.delete",)
    reversible: ClassVar[bool] = True

    def merge_patch(self, payload: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """A typed position number is kept as typed; clearing it numbers the line automatically again."""
        merged = {**payload, **patch}
        if "ordinal" in patch:
            merged["ordinal_auto"] = not str(patch.get("ordinal") or "").strip()
        return merged

    def edit_view(self, payload: dict[str, Any]) -> dict[str, Any]:
        """An automatic number re-assigned at apply time is not a human edit."""
        view = dict(payload)
        if view.pop("ordinal_auto", False):
            view.pop("ordinal", None)
        return view

    async def build(
        self,
        ctx: ActionContext,
        args: dict[str, Any],
        *,
        prior: ChatAction | None = None,
    ) -> ActionDraft:
        project = await resolve_project(ctx, args)
        bill = await resolve_bill(ctx, project.id, args)
        if bill.is_locked:
            raise ActionConflictError(code="locked", params={"boq": bill.name})

        errors = FieldErrors()
        description = parse_text(args, "description", errors, required=True, max_length=5000)
        unit = parse_text(args, "unit", errors, required=True, max_length=20)
        quantity = parse_decimal(args, "quantity", errors, required=True)
        unit_rate = parse_decimal(args, "unit_rate", errors)
        if unit_rate is None and "unit_rate" not in errors.errors:
            unit_rate = Decimal("0")

        lines = await bill_lines(ctx, bill.id)
        section, no_sections = _resolve_section(lines, args)

        used = {line.ordinal for line in lines}
        reserved = {
            str(p.get("ordinal"))
            for p in await pending_payloads(
                ctx,
                action_type=self.action_type,
                project_id=project.id,
                exclude_id=prior.id if prior is not None else None,
            )
            if p.get("boq_id") == str(bill.id) and p.get("ordinal")
        }
        typed_ordinal = str(args.get("ordinal") or "").strip()
        auto = bool(args["ordinal_auto"]) if "ordinal_auto" in args else not typed_ordinal
        if auto:
            keep = typed_ordinal and typed_ordinal not in used and typed_ordinal not in reserved
            ordinal = typed_ordinal if keep else next_ordinal(section, used | reserved)
        else:
            ordinal = parse_text(args, "ordinal", errors, required=True, max_length=50) or ""
            if ordinal in used:
                errors.add("ordinal", "ordinal_taken")
        errors.raise_if_any()

        total = line_total(quantity, unit_rate)
        payload = {
            "project_id": str(project.id),
            "boq_id": str(bill.id),
            "section_id": str(section.id) if section is not None else None,
            "ordinal": ordinal,
            "ordinal_auto": auto,
            "description": description,
            "unit": unit,
            "quantity": decimal_str(quantity),
            "unit_rate": decimal_str(unit_rate),
        }
        currency = project.currency or None
        fields = [
            make_field("description", "longtext", description, editable=True, required=True),
            make_field("quantity", "number", to_number(quantity), unit=unit, editable=True, required=True),
            make_field("unit", "text", unit, editable=True, required=True),
            make_field("unit_rate", "money", to_number(unit_rate), currency=currency, editable=True),
            make_field("total", "money", to_number(total), currency=currency),
            make_field("ordinal", "text", ordinal, editable=True),
            make_field("section", "ref", section.label if section is not None else None),
        ]
        notes = [make_note("top_level_position", field_key="section")] if no_sections else []
        return ActionDraft(
            payload=payload,
            fields=fields,
            project_id=project.id,
            subtitle=bill.name,
            notes=notes,
        )

    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        ctx.require_permissions(self.apply_permissions)
        boq_id = coerce_uuid(payload.get("boq_id"))
        if boq_id is None:
            raise ActionNotFoundError(code="boq_not_found")
        await verify_bill_access(ctx, boq_id)

    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        from app.modules.boq.schemas import PositionCreate
        from app.modules.boq.service import BOQService

        payload = draft.payload
        boq_id = uuid.UUID(payload["boq_id"])
        project_id = coerce_uuid(payload.get("project_id"))
        metadata = {
            "via": "ai_assistant",
            "ai_action_id": str(action.id),
            "requested_by": str(action.requested_by),
            "approved_by": str(ctx.user_id),
        }
        data = PositionCreate(
            boq_id=boq_id,
            parent_id=coerce_uuid(payload.get("section_id")),
            ordinal=payload["ordinal"],
            description=payload["description"],
            unit=payload["unit"],
            quantity=float(Decimal(payload["quantity"])),
            unit_rate=Decimal(payload["unit_rate"]),
            source=AI_SOURCE,
            confidence=action.confidence,
            metadata=metadata,
        )
        service = BOQService(ctx.session)
        position = await service.add_position(data)
        await _write_route_activity(
            service,
            user_id=ctx.user_id,
            action="position_added",
            description=f"Added position '{(payload['description'] or '')[:60]}'",
            project_id=project_id,
            boq_id=boq_id,
            target_id=position.id,
            metadata=metadata,
        )
        after_state = position_state(position)
        after_state["boq_id"] = str(boq_id)
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(position.id),
            label=f"{position.ordinal} {(position.description or '')[:60]}".strip(),
            url=position_url(boq_id, position.id),
            after_state=after_state,
            audit_action="created",
        )

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        ctx.require_permissions(self.revert_permissions)
        position_id = coerce_uuid(action.applied_entity_id)
        line = await get_line(ctx, position_id) if position_id is not None else None
        if line is None:
            raise ActionConflictError(code="target_missing")
        await verify_bill_access(ctx, line.boq_id)

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        from app.modules.boq.service import BOQService

        position_id = coerce_uuid(action.applied_entity_id)
        line = await get_line(ctx, position_id) if position_id is not None else None
        if line is None:
            raise ActionConflictError(code="target_missing")
        applied_state = (action.result or {}).get("after_state") or {}
        current = line.state()
        if any(not same_value(current[key], applied_state.get(key)) for key in _TRACKED):
            raise ActionConflictError(code="changed_since_apply")
        bill = await get_bill(ctx, line.boq_id)
        if bill is not None and bill.is_locked:
            raise ActionConflictError(code="locked", params={"boq": bill.name})
        service = BOQService(ctx.session)
        await _write_route_activity(
            service,
            user_id=ctx.user_id,
            action="position_deleted",
            description=f"Deleted position {line.id} (cascade=False)",
            project_id=bill.project_id if bill is not None else None,
            boq_id=line.boq_id,
            target_id=line.id,
            metadata={
                "via": "ai_assistant",
                "ai_action_id": str(action.id),
                "undo_of": "boq.add_position",
            },
        )
        await service.delete_position(line.id, cascade=False)
        return None
