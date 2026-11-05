# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Waste factor validation rules (rule set ``waste_factors``).

Rules run over a plain dict context built by the service::

    {
        "factor": {"id", "category", "label", "factor", "tenant_id"},
        "siblings": [{"id", "category", "tenant_id"}],   # other rows of the same trimmed, case-folded category
    }

The apply endpoint resolves a factor by category, so the category is the key: two
rows under one key make the gross quantity depend on write order.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, section, to_dec

WASTE_FACTORS_RULE_SET = "waste_factors"

#: Beyond 50 % extra, the allowance is no longer waste: it is a different material or a slipped decimal.
HIGH_FACTOR = Decimal("1.5")


class _WasteRule(MoneyRule):
    standard = WASTE_FACTORS_RULE_SET
    message_section = "waste_factors"
    own_message_keys = frozenset({"duplicate_category", "category_case_variant", "factor_high"})
    suggestion_key = "waste_factors.suggestion"


def _ref(context: ValidationContext) -> str:
    return str(section(context, "factor").get("id", ""))


def _key(value: object) -> str:
    return str(value or "").strip()


class UniqueCategoryRule(_WasteRule):
    """One factor per category and tenant scope."""

    rule_id = "waste_factors.unique_category"
    name = "Waste factor category is unique"
    description = "Two factors with the same category make the net-to-gross result depend on write order"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        head = section(context, "factor")
        ref = _ref(context)
        same = [
            s
            for s in rows(context, "siblings")
            if _key(s.get("category")) == _key(head.get("category"))
            and str(s.get("tenant_id") or "") == str(head.get("tenant_id") or "")
        ]
        if same:
            return [self.fail(context, "duplicate_category", ref=ref, category=_key(head.get("category")))]
        return [self.ok(ref)]


class CategoryCaseVariantRule(_WasteRule):
    """A category that differs from an existing one only in case never matches the same lines."""

    rule_id = "waste_factors.category_case_variant"
    name = "Waste factor category matches existing spelling"
    severity = Severity.WARNING
    description = "Categories are matched exactly, so 'Concrete' and 'concrete' are two different keys"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        head = section(context, "factor")
        ref = _ref(context)
        mine = _key(head.get("category"))
        variants = sorted({_key(s.get("category")) for s in rows(context, "siblings")} - {mine, ""})
        if variants:
            return [self.fail(context, "category_case_variant", ref=ref, category=mine, existing=", ".join(variants))]
        return [self.ok(ref)]


class FactorPlausibleRule(_WasteRule):
    """A waste allowance stays within what a site really loses."""

    rule_id = "waste_factors.factor_plausible"
    name = "Waste factor is plausible"
    severity = Severity.WARNING
    description = "A factor above 1.5 means more than 50 percent is ordered on top of the drawn quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        head = section(context, "factor")
        value = to_dec(head.get("factor"))
        if value is not None and value > HIGH_FACTOR:
            return [
                self.fail(
                    context,
                    "factor_high",
                    ref=_ref(context),
                    category=_key(head.get("category")),
                    factor=value,
                    pct=(value - 1) * 100,
                )
            ]
        return [self.ok(_ref(context))]


WASTE_FACTORS_RULES = (UniqueCategoryRule, CategoryCaseVariantRule, FactorPlausibleRule)


def register_waste_factors_validation_rules() -> None:
    """Register the waste factor rules with the platform rule registry."""
    for rule_class in WASTE_FACTORS_RULES:
        rule_registry.register(rule_class(), [WASTE_FACTORS_RULE_SET])
