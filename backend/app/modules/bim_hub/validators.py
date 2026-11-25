# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Model-to-BOQ link rules (rule set ``bim_link``).

They run over the link check of one model that
:meth:`app.modules.bim_hub.service.BIMHubService.link_check` assembles::

    {"model": {"id", "name", "version"},
     "unlinked_by_type": [{"element_type", "count"}],
     "positions": [{"id", "ordinal", "unit", "linked", "status"}]}

``positions`` are the BOQ lines bound to the model (``cad_model_id``) or linked
to any of its elements. ``status`` is the one the last quantity sync recorded
(``ok``, ``no_quantity``, ``unit_unsupported``), empty when never synced.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, section

BIM_LINK_RULE_SET = "bim_link"

#: Findings listed per rule; the payload keeps the full counts.
MAX_FINDINGS_PER_RULE = 50


class _LinkRule(MoneyRule):
    standard = BIM_LINK_RULE_SET
    message_section = BIM_LINK_RULE_SET
    suggestion_key = "bim_link.suggestion"


def _model_label(context: ValidationContext) -> str:
    model = section(context, "model")
    name = str(model.get("name") or model.get("id") or "")
    version = str(model.get("version") or "").strip()
    return f"{name} v{version}" if version else name


class ElementsLinkedRule(_LinkRule):
    """Every element of the model reaches the bill, or the gap is visible."""

    rule_id = "bim_link.elements_linked"
    name = "Model elements are linked to the BOQ"
    severity = Severity.WARNING
    description = "Elements linked to no BOQ position are missing from the estimate"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        model = _model_label(context)
        out = [
            self.fail(
                context,
                "elements_unlinked",
                ref=str(row.get("element_type") or ""),
                model=model,
                element_type=str(row.get("element_type") or "-"),
                count=int(row.get("count") or 0),
            )
            for row in rows(context, "unlinked_by_type")
            if int(row.get("count") or 0) > 0
        ][:MAX_FINDINGS_PER_RULE]
        return out or [self.ok(model)]


class PositionsHaveElementsRule(_LinkRule):
    """A line bound to the model still has elements linked to it."""

    rule_id = "bim_link.positions_have_elements"
    name = "Model positions have elements"
    severity = Severity.WARNING
    description = "A position bound to a model with no linked element has a quantity nothing in the model supports"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        model = _model_label(context)
        out = [
            self.fail(
                context, "position_no_elements", ref=str(p.get("id") or ""), ordinal=p.get("ordinal"), model=model
            )
            for p in rows(context, "positions")
            if int(p.get("linked") or 0) == 0
        ][:MAX_FINDINGS_PER_RULE]
        return out or [self.ok(model)]


class UnitSuppliedRule(_LinkRule):
    """The position's unit is one the linked elements measure."""

    rule_id = "bim_link.unit_supplied"
    name = "Model supplies the position unit"
    severity = Severity.ERROR
    description = "Linked elements carry no value in the dimension of the position unit, so no quantity was taken"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        model = _model_label(context)
        out = [
            self.fail(
                context,
                "unit_no_quantity",
                ref=str(p.get("id") or ""),
                ordinal=p.get("ordinal"),
                unit=p.get("unit") or "-",
                count=int(p.get("linked") or 0),
            )
            for p in rows(context, "positions")
            if int(p.get("linked") or 0) > 0 and p.get("status") in ("no_quantity", "unit_unsupported")
        ][:MAX_FINDINGS_PER_RULE]
        return out or [self.ok(model)]


BIM_LINK_RULES = (ElementsLinkedRule, PositionsHaveElementsRule, UnitSuppliedRule)


def register_bim_link_validation_rules() -> None:
    """Register the model-to-BOQ link rules with the platform rule registry."""
    for rule_class in BIM_LINK_RULES:
        rule_registry.register(rule_class(), [BIM_LINK_RULE_SET])


__all__ = ["BIM_LINK_RULES", "BIM_LINK_RULE_SET", "register_bim_link_validation_rules"]
