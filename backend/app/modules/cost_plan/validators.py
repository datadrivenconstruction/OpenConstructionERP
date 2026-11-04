# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost plan validation rules (rule set ``cost_plan``).

The plan is a regrouping of a bill, so the rules check that the regrouping
lost nothing and that the figure is fit to be read as an estimate. They run
over a plain dict built from the finished plan::

    {"plan": {"id", "currency", "gifa", "direct_cost", "grand_total", "markups_total",
              "allocated_total", "unallocated_total", "unallocated_count",
              "building_works_total"}}

A plan of an empty or all-zero bill carries no money, so no rule fires on it.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, currency_of, section, to_dec

COST_PLAN_RULE_SET = "cost_plan"

#: Positions without a usable NRM 1 code above this share of the direct cost make the elemental split unreliable.
UNALLOCATED_WARN_PERCENT = Decimal("5")


class _PlanRule(MoneyRule):
    standard = COST_PLAN_RULE_SET
    message_section = "cost_rules"
    own_message_keys = frozenset({"unallocated_share", "gifa_missing", "markup_load"})


def _plan(context: ValidationContext) -> tuple[dict, str]:
    plan = section(context, "plan")
    return plan, str(plan.get("id", ""))


def _num(plan: dict, key: str) -> Decimal:
    return to_dec(plan.get(key)) or Decimal("0")


class PlanTiesToBillRule(_PlanRule):
    """Elements, add-ons and unallocated positions add up to the direct cost, and markups to the total."""

    rule_id = "cost_plan.ties_to_bill"
    name = "Cost plan ties to the bill"
    description = "Allocated + unallocated equals the direct cost; direct cost + markups equals the grand total"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan, ref = _plan(context)
        currency = currency_of(plan)
        out: list[RuleResult] = []
        parts = _num(plan, "allocated_total") + _num(plan, "unallocated_total")
        bad = self.total_mismatch(context, ref, "direct cost", _num(plan, "direct_cost"), parts, currency)
        if bad:
            out.append(bad)
        bad = self.total_mismatch(
            context,
            ref,
            "grand total",
            _num(plan, "grand_total"),
            _num(plan, "direct_cost") + _num(plan, "markups_total"),
            currency,
        )
        if bad:
            out.append(bad)
        return out or [self.ok(ref)]


class PlanCurrencyRule(_PlanRule):
    """A cost plan that carries money states the currency it is in."""

    rule_id = "cost_plan.currency_stated"
    name = "Cost plan currency stated"
    description = "A plan with a non-zero total needs the project currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan, ref = _plan(context)
        if _num(plan, "grand_total") != 0 and not currency_of(plan):
            return [self.fail(context, "currency_present", ref=ref)]
        return [self.ok(ref)]


class UnallocatedShareRule(_PlanRule):
    """Few positions are left without an NRM 1 element."""

    rule_id = "cost_plan.unallocated_share"
    name = "Unallocated share of the plan is small"
    severity = Severity.WARNING
    description = "More than 5 % of the direct cost on positions with no usable NRM 1 code is flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan, ref = _plan(context)
        direct = _num(plan, "direct_cost")
        if direct <= 0:
            return [self.ok(ref)]
        share = (_num(plan, "unallocated_total") * 100 / direct).quantize(Decimal("0.1"))
        if share <= UNALLOCATED_WARN_PERCENT:
            return [self.ok(ref)]
        return [self.fail(context, "unallocated_share", ref=ref, share=share, count=plan.get("unallocated_count", 0))]


class GifaMissingRule(_PlanRule):
    """Building works are priced, so the plan can be benchmarked per m2 of floor area."""

    rule_id = "cost_plan.gifa_stated"
    name = "Floor area stated for the cost per m2"
    severity = Severity.WARNING
    description = "A plan with building works and no GIFA cannot show cost per m2"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan, ref = _plan(context)
        if _num(plan, "building_works_total") > 0 and (to_dec(plan.get("gifa")) or 0) <= 0:
            return [self.fail(context, "gifa_missing", ref=ref)]
        return [self.ok(ref)]


class MarkupLoadRule(_PlanRule):
    """Overheads, profit, risk and escalation together stay below the direct cost."""

    rule_id = "cost_plan.markup_load"
    name = "Markup load is plausible"
    severity = Severity.WARNING
    description = "Markups adding up to more than the direct cost itself are flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan, ref = _plan(context)
        direct = _num(plan, "direct_cost")
        if direct <= 0 or _num(plan, "markups_total") <= direct:
            return [self.ok(ref)]
        percent = (_num(plan, "markups_total") * 100 / direct).quantize(Decimal("1"))
        return [self.fail(context, "markup_load", ref=ref, percent=percent)]


COST_PLAN_RULES = (
    PlanTiesToBillRule,
    PlanCurrencyRule,
    UnallocatedShareRule,
    GifaMissingRule,
    MarkupLoadRule,
)


def register_cost_plan_validation_rules() -> None:
    """Register the cost plan rules with the platform rule registry."""
    for rule_class in COST_PLAN_RULES:
        rule_registry.register(rule_class(), [COST_PLAN_RULE_SET])


__all__ = ["COST_PLAN_RULES", "COST_PLAN_RULE_SET", "register_cost_plan_validation_rules"]
