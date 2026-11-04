# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change order validation rules (rule set ``changeorders``).

Rules run over a plain dict context built by the caller::

    {
        "change_order": {"id", "project_id", "code", "status", "previous_status",
                        "cost_impact", "currency", "schedule_impact_days"},
        "items": [{"id", "original_quantity", "new_quantity", "original_rate",
                   "new_rate", "cost_delta", "currency"}],
    }
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import (
    MAX_SANE_AMOUNT,
    MONEY_TOLERANCE,
    MoneyRule,
    blank,
    currency_of,
    rows,
    section,
    to_dec,
)
from app.modules.changeorders.service import VALID_TRANSITIONS

CHANGEORDERS_RULE_SET = "changeorders"

#: A scope change can run for years, not for a century.
MAX_SCHEDULE_DAYS = Decimal("3650")


class ChangeOrderTotalMatchesItemsRule(MoneyRule):
    """The cost impact equals the sum of the item deltas, and each delta follows its numbers."""

    rule_id = "changeorders.total_matches_items"
    name = "Change order total equals the sum of its items"
    standard = CHANGEORDERS_RULE_SET
    description = "cost_impact must equal the item deltas, and each delta new qty x rate minus original"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        co = section(context, "change_order")
        items = rows(context, "items")
        ref = str(co.get("id", ""))
        currency = currency_of(co)
        out: list[RuleResult] = []
        total = Decimal("0")
        for item in items:
            delta = to_dec(item.get("cost_delta"))
            if delta is None:
                continue
            total += delta
            parts = [to_dec(item.get(k)) for k in ("original_quantity", "new_quantity", "original_rate", "new_rate")]
            if any(p is None for p in parts):
                continue
            oq, nq, orate, nrate = parts
            bad = self.total_mismatch(
                context, str(item.get("id", ref)), "item", delta, nq * nrate - oq * orate, currency
            )
            if bad:
                out.append(bad)
        stated = to_dec(co.get("cost_impact"))
        if stated is not None and items:
            bad = self.total_mismatch(context, ref, "change order", stated, total, currency)
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class ChangeOrderRangesRule(MoneyRule):
    """Quantities and rates are non-negative and below the unit-slip ceiling."""

    rule_id = "changeorders.values_in_range"
    name = "Change order quantities and rates are sane"
    standard = CHANGEORDERS_RULE_SET
    description = "Item quantities and rates must be between 0 and 1e12; schedule impact within +-3650 days"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        co = section(context, "change_order")
        out: list[RuleResult] = []
        for item in rows(context, "items"):
            for field in ("original_quantity", "new_quantity", "original_rate", "new_rate"):
                bad = self.out_of_range(
                    context, str(item.get("id", "")), field, to_dec(item.get(field)), Decimal("0"), MAX_SANE_AMOUNT
                )
                if bad:
                    out.append(bad)
        bad = self.out_of_range(
            context,
            str(co.get("id", "")),
            "schedule_impact_days",
            to_dec(co.get("schedule_impact_days")),
            -MAX_SCHEDULE_DAYS,
            MAX_SCHEDULE_DAYS,
        )
        if bad:
            out.append(bad)
        return out or [self.ok(str(co.get("id", "")))]


class ChangeOrderCurrencyRule(MoneyRule):
    """A change order that carries money states one currency, the same on every item."""

    rule_id = "changeorders.currency_consistent"
    name = "Change order currency stated and consistent"
    standard = CHANGEORDERS_RULE_SET
    description = "Currency must be present on a change order with a cost impact and match its items"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        co = section(context, "change_order")
        ref = str(co.get("id", ""))
        impact = to_dec(co.get("cost_impact"))
        items = rows(context, "items")
        carries_money = (impact is not None and impact != 0) or any(
            (to_dec(i.get("cost_delta")) or 0) != 0 for i in items
        )
        if not carries_money:
            return [self.ok(ref)]
        found = self.currency_findings(context, ref, currency_of(co), [currency_of(i) for i in items])
        return found or [self.ok(ref)]


class ChangeOrderReferencesRule(MoneyRule):
    """A change order names its project and carries a code."""

    rule_id = "changeorders.references_present"
    name = "Change order references present"
    standard = CHANGEORDERS_RULE_SET
    severity = Severity.ERROR
    description = "project_id and code are required"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        co = section(context, "change_order")
        ref = str(co.get("id", ""))
        out = [
            self.fail(context, "reference_present", ref=ref, field=field)
            for field in ("project_id", "code")
            if blank(co.get(field))
        ]
        return out or [self.ok(ref)]


class ChangeOrderStatusTransitionRule(MoneyRule):
    """The status moved along an edge of the change order workflow."""

    rule_id = "changeorders.status_transition"
    name = "Change order status transition allowed"
    standard = CHANGEORDERS_RULE_SET
    description = "draft -> submitted -> approved/rejected -> executed; no skipping, nothing after executed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        co = section(context, "change_order")
        ref = str(co.get("id", ""))
        found = self.status_findings(context, ref, co.get("previous_status"), co.get("status"), VALID_TRANSITIONS)
        return found or [self.ok(ref)]


CHANGEORDERS_RULES = (
    ChangeOrderTotalMatchesItemsRule,
    ChangeOrderRangesRule,
    ChangeOrderCurrencyRule,
    ChangeOrderReferencesRule,
    ChangeOrderStatusTransitionRule,
)


def register_changeorders_validation_rules() -> None:
    """Register the change order rules with the platform rule registry."""
    for rule_class in CHANGEORDERS_RULES:
        rule_registry.register(rule_class(), [CHANGEORDERS_RULE_SET])


__all__ = ["CHANGEORDERS_RULES", "CHANGEORDERS_RULE_SET", "MONEY_TOLERANCE", "register_changeorders_validation_rules"]
