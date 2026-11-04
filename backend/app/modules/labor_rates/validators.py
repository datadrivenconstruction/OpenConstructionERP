# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Labor rate validation rules (rule set ``labor_rates``).

Rules run over a plain dict context built by the service::

    {
        "template": {"id", "name", "base_wage", "currency"},
        "components": [{"label", "kind", "value"}],
        "crew": {"id", "currency", "members": [{"trade", "count", "all_in_rate"}]},
    }

Any section may be absent; a rule only judges what is present, so a half-filled
template or an empty crew is never refused for what it has not got yet.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MAX_SANE_AMOUNT, MoneyRule, currency_of, rows, section, to_dec

LABOR_RATES_RULE_SET = "labor_rates"

#: One on-cost line above this is a slipped decimal (30 typed as 3000), not a charge.
MAX_ONCOST_PERCENT = Decimal("300")
#: Statutory charges, insurance, holiday and sick pay together rarely pass this share of the wage.
BURDEN_WARN_PERCENT = Decimal("150")


class _LaborRule(MoneyRule):
    standard = LABOR_RATES_RULE_SET
    message_section = "cost_rules"
    own_message_keys = frozenset({"burden_high", "duplicate_line"})


def _ref(context: ValidationContext) -> str:
    return str(section(context, "template").get("id") or section(context, "crew").get("id") or "")


def _crew_rows(context: ValidationContext) -> list[dict]:
    members = section(context, "crew").get("members")
    return [m for m in members if isinstance(m, dict)] if isinstance(members, list) else []


class OnCostInRangeRule(_LaborRule):
    """A percentage on-cost lies in 0..300 and a fixed one is a non-negative amount."""

    rule_id = "labor_rates.oncost_in_range"
    name = "On-cost values are in a sane range"
    description = "Percentage on-costs 0 to 300; fixed hourly on-costs 0 to 1e12; none negative"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        out: list[RuleResult] = []
        for line in rows(context, "components"):
            high = MAX_ONCOST_PERCENT if str(line.get("kind") or "percentage") == "percentage" else MAX_SANE_AMOUNT
            bad = self.out_of_range(
                context, ref, str(line.get("label") or "on-cost"), to_dec(line.get("value")), Decimal("0"), high
            )
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class CrewRatesInRangeRule(_LaborRule):
    """A crew member's all-in hourly rate is not negative and not a unit slip."""

    rule_id = "labor_rates.crew_rate_in_range"
    name = "Crew hourly rates are in a sane range"
    description = "Each crew line's all-in rate between 0 and 1e12"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        out: list[RuleResult] = []
        for m in _crew_rows(context):
            bad = self.out_of_range(
                context,
                ref,
                str(m.get("trade") or "rate"),
                to_dec(m.get("all_in_rate")),
                Decimal("0"),
                MAX_SANE_AMOUNT,
            )
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class BurdenPlausibleRule(_LaborRule):
    """The percentage on-costs together do not load the wage beyond what site labour carries."""

    rule_id = "labor_rates.burden_plausible"
    name = "Total on-cost burden is plausible"
    severity = Severity.WARNING
    description = "Percentage on-costs adding up to more than 150 % of the base wage are flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        total = Decimal("0")
        for line in rows(context, "components"):
            value = to_dec(line.get("value"))
            if value is not None and str(line.get("kind") or "percentage") == "percentage":
                total += value
        if total <= BURDEN_WARN_PERCENT:
            return [self.ok(ref)]
        shown = format(total.normalize(), "f")
        return [self.fail(context, "burden_high", ref=ref, percent=shown, limit=BURDEN_WARN_PERCENT)]


class LaborCurrencyRule(_LaborRule):
    """A rate that carries money names its currency."""

    rule_id = "labor_rates.currency_stated"
    name = "Labor rate currency stated"
    severity = Severity.WARNING
    description = "A template with a base wage, or a crew with priced lines, needs a currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        template = section(context, "template")
        priced_template = (to_dec(template.get("base_wage")) or 0) > 0
        priced_crew = any((to_dec(m.get("all_in_rate")) or 0) > 0 for m in _crew_rows(context))
        if priced_template and not currency_of(template):
            return [self.fail(context, "currency_present", ref=ref)]
        if priced_crew and not currency_of(section(context, "crew")):
            return [self.fail(context, "currency_present", ref=ref)]
        return [self.ok(ref)]


class DuplicateLinesRule(_LaborRule):
    """The same on-cost or the same trade is not listed twice, which would load the rate twice."""

    rule_id = "labor_rates.duplicate_lines"
    name = "No duplicated on-cost or crew line"
    severity = Severity.WARNING
    description = "An on-cost label or a crew trade appearing more than once is flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        out: list[RuleResult] = []
        for items, key in ((rows(context, "components"), "label"), (_crew_rows(context), "trade")):
            seen: set[str] = set()
            for item in items:
                label = str(item.get(key) or "").strip()
                norm = label.casefold()
                if not norm:
                    continue
                if norm in seen:
                    out.append(self.fail(context, "duplicate_line", ref=ref, label=label))
                seen.add(norm)
        return out or [self.ok(ref)]


LABOR_RATES_RULES = (
    OnCostInRangeRule,
    CrewRatesInRangeRule,
    BurdenPlausibleRule,
    LaborCurrencyRule,
    DuplicateLinesRule,
)


def register_labor_rates_validation_rules() -> None:
    """Register the labor rate rules with the platform rule registry."""
    for rule_class in LABOR_RATES_RULES:
        rule_registry.register(rule_class(), [LABOR_RATES_RULE_SET])


__all__ = ["LABOR_RATES_RULES", "LABOR_RATES_RULE_SET", "register_labor_rates_validation_rules"]
