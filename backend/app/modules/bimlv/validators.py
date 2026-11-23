# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM-LV container validation rules (rule set ``bimlv``, DIN SPEC 91350).

A container ties priced LV positions to model elements, so the rules check that
the link table is unambiguous and that every link lands on something. They run
over a plain dict built from the parsed container, and again with the outcome of
the link materialisation once the project has been searched::

    {"container": {"positions": [{"ordinal", "quantity", "unit_rate"}],
                   "mapping": {ordinal: [guid, ...]},
                   "model_ref": {"filename", "model_id", "guid"}},
     "result": {"unmatched_ordinals": [...], "unmatched_guids": [...]}}     # optional

An empty container carries no links, so no rule fires on it. Messages come from the shared
``money`` and ``cost_rules`` sections.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MAX_SANE_AMOUNT, MoneyRule, section, to_dec

BIMLV_RULE_SET = "bimlv"

#: Findings listed per rule before the rest are summarised by the count in the result itself.
MAX_FINDINGS_PER_RULE = 20


class _ContainerRule(MoneyRule):
    standard = BIMLV_RULE_SET


def _container(context: ValidationContext) -> dict:
    return section(context, "container")


def _mapping(context: ValidationContext) -> dict:
    mapping = _container(context).get("mapping")
    return mapping if isinstance(mapping, dict) else {}


def _ref(context: ValidationContext) -> str:
    return str(_container(context).get("project_id", ""))


class UniqueOrdinalsRule(_ContainerRule):
    """An ordinal names one LV position, so the link table can resolve it."""

    rule_id = "bimlv.ordinals_unique"
    name = "LV ordinals are unique"
    description = "Two positions with the same ordinal make the link table ambiguous"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        counts = Counter(str(p.get("ordinal", "")).strip() for p in _positions(context))
        out = [
            self.fail(context, "duplicate_line", ref=ordinal, section="cost_rules", label=f"Position {ordinal}")
            for ordinal, n in counts.items()
            if ordinal and n > 1
        ][:MAX_FINDINGS_PER_RULE]
        return out or [self.ok(ref)]


def _positions(context: ValidationContext) -> list[dict]:
    value = _container(context).get("positions")
    return [p for p in value if isinstance(p, dict)] if isinstance(value, list) else []


class PositionFiguresRule(_ContainerRule):
    """Quantities and unit rates are not negative and not a unit slip."""

    rule_id = "bimlv.position_figures_sane"
    name = "LV quantities and rates are sane"
    description = "Quantity and unit rate lie between zero and a figure no construction line reaches"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        out: list[RuleResult] = []
        for position in _positions(context):
            ordinal = str(position.get("ordinal", ""))
            for key in ("quantity", "unit_rate"):
                bad = self.out_of_range(
                    context, ordinal, f"{key} of {ordinal}", to_dec(position.get(key)), Decimal(0), MAX_SANE_AMOUNT
                )
                if bad:
                    out.append(bad)
        return out[:MAX_FINDINGS_PER_RULE] or [self.ok(ref)]


class LinksHitPositionsRule(_ContainerRule):
    """Every link starts at a position the container's own LV contains."""

    rule_id = "bimlv.links_hit_positions"
    name = "Links start at LV positions"
    description = "A link-table ordinal that is not in the LV points at nothing"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        known = {str(p.get("ordinal", "")).strip() for p in _positions(context)}
        if not known:
            return [self.ok(ref)]
        out = [
            self.fail(context, "reference_present", ref=str(ordinal), field=f"LV position {ordinal}")
            for ordinal in _mapping(context)
            if str(ordinal).strip() not in known
        ][:MAX_FINDINGS_PER_RULE]
        return out or [self.ok(ref)]


class ModelReferenceRule(_ContainerRule):
    """A container that links elements says which model they belong to."""

    rule_id = "bimlv.model_reference_stated"
    name = "Model reference stated"
    severity = Severity.WARNING
    description = "Links without a model file name, id or GUID cannot be traced back to the model"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        linked = any(guids for guids in _mapping(context).values())
        model_ref = _container(context).get("model_ref")
        model_ref = model_ref if isinstance(model_ref, dict) else {}
        if linked and not any(str(model_ref.get(k) or "").strip() for k in ("filename", "model_id", "guid")):
            return [self.fail(context, "reference_present", ref=ref, field="model reference")]
        return [self.ok(ref)]


class LinksMaterialiseRule(_ContainerRule):
    """Ordinals and element GUIDs of the link table exist in the project."""

    rule_id = "bimlv.links_resolve_in_project"
    name = "Links resolve in the project"
    severity = Severity.WARNING
    description = "Ordinals without a BOQ position or GUIDs without a BIM element create no link"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        result = section(context, "result")
        out: list[RuleResult] = []
        for ordinal in (result.get("unmatched_ordinals") or [])[:MAX_FINDINGS_PER_RULE]:
            out.append(self.fail(context, "reference_present", ref=str(ordinal), field=f"BOQ position {ordinal}"))
        room = MAX_FINDINGS_PER_RULE - len(out)
        for guid in (result.get("unmatched_guids") or [])[: max(room, 0)]:
            out.append(self.fail(context, "reference_present", ref=str(guid), field=f"BIM element {guid}"))
        return out or [self.ok(ref)]


BIMLV_RULES = (
    UniqueOrdinalsRule,
    PositionFiguresRule,
    LinksHitPositionsRule,
    ModelReferenceRule,
    LinksMaterialiseRule,
)


def register_bimlv_validation_rules() -> None:
    """Register the BIM-LV rules with the platform rule registry."""
    for rule_class in BIMLV_RULES:
        rule_registry.register(rule_class(), [BIMLV_RULE_SET])


__all__ = ["BIMLV_RULES", "BIMLV_RULE_SET", "register_bimlv_validation_rules"]
