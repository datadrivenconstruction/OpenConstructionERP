# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM requirements validation rules (rule set ``bim_requirements``).

Requirement sets are only ever created by importing a file (IDS, COBie, BIMQ, Excel, Revit shared
parameters, YAML rule pack), so the rules run over the whole batch before anything is stored::

    {"requirements": [{"row", "property_name", "element_filter", "constraint_def"}, ...]}

An error refuses the whole import with a coded 422 (a standards file is taken whole or not at all);
warnings come back with the import result.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, rows, to_dec
from app.core.validation.quality_rules import gate_rule_set, warning_findings

BIM_REQUIREMENTS_RULE_SET = "bim_requirements"


def _bound(value: Any) -> Any:
    return to_dec(value.replace(",", ".") if isinstance(value, str) else value)


class _BimRule(MoneyRule):
    standard = BIM_REQUIREMENTS_RULE_SET
    message_section = "bim_requirements"


class PropertyNamedRule(_BimRule):
    """Every requirement names the property it checks."""

    rule_id = "bim_requirements.property_named"
    name = "BIM requirement names its property"
    description = "property_name must not be blank"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "property_missing", ref=str(r.get("row", "")), row=r.get("row", ""))
            for r in rows(context, "requirements")
            if blank(r.get("property_name"))
        ]
        return out or [self.ok("")]


class BoundsOrderedRule(_BimRule):
    """A numeric limit has its minimum under its maximum."""

    rule_id = "bim_requirements.bounds_ordered"
    name = "BIM requirement minimum is not above its maximum"
    description = "constraint_def min must not exceed max"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for r in rows(context, "requirements"):
            cdef = r.get("constraint_def")
            cdef = cdef if isinstance(cdef, dict) else {}
            low, high = _bound(cdef.get("min")), _bound(cdef.get("max"))
            if low is not None and high is not None and low > high:
                out.append(
                    self.fail(
                        context,
                        "bounds_inverted",
                        ref=str(r.get("row", "")),
                        row=r.get("row", ""),
                        property=r.get("property_name") or "?",
                        low=low,
                        high=high,
                    )
                )
        return out or [self.ok("")]


class PatternCompilesRule(_BimRule):
    """A pattern restriction is a regular expression that can be run."""

    rule_id = "bim_requirements.pattern_compiles"
    name = "BIM requirement pattern is a valid expression"
    description = "constraint_def pattern must compile"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for r in rows(context, "requirements"):
            cdef = r.get("constraint_def")
            pattern = cdef.get("pattern") if isinstance(cdef, dict) else None
            if not isinstance(pattern, str) or not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error:
                out.append(
                    self.fail(
                        context,
                        "pattern_invalid",
                        ref=str(r.get("row", "")),
                        row=r.get("row", ""),
                        property=r.get("property_name") or "?",
                        pattern=pattern,
                    )
                )
        return out or [self.ok("")]


class ElementFilterPresentRule(_BimRule):
    """A requirement says which elements it applies to."""

    rule_id = "bim_requirements.element_filter_present"
    name = "BIM requirement targets some elements"
    severity = Severity.WARNING
    description = "a requirement with an empty element_filter applies to every element in the model"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        unfiltered = [r for r in rows(context, "requirements") if not r.get("element_filter")]
        if unfiltered:
            return [self.fail(context, "filter_empty", count=len(unfiltered), total=len(rows(context, "requirements")))]
        return [self.ok("")]


BIM_REQUIREMENTS_RULES = (
    PropertyNamedRule,
    BoundsOrderedRule,
    PatternCompilesRule,
    ElementFilterPresentRule,
)


def register_bim_requirements_validation_rules() -> None:
    """Register the BIM requirements rules with the platform rule registry."""
    for rule_class in BIM_REQUIREMENTS_RULES:
        rule_registry.register(rule_class(), [BIM_REQUIREMENTS_RULE_SET])


async def gate_import(
    batch: list[dict[str, Any]], *, operation: str, project_id: Any, subject: str
) -> list[dict[str, Any]]:
    """Run the rule set over an import batch; errors raise the coded 422, the warnings are returned."""
    report = await gate_rule_set(
        rule_set=BIM_REQUIREMENTS_RULE_SET,
        data={"requirements": batch},
        target_type="bim_requirements_import",
        target_id="",
        project_id=project_id,
        operation=operation,
        subject=subject,
        error="bim_requirements_rules_failed",
    )
    return warning_findings(report)


__all__ = [
    "BIM_REQUIREMENTS_RULES",
    "BIM_REQUIREMENTS_RULE_SET",
    "gate_import",
    "register_bim_requirements_validation_rules",
]
