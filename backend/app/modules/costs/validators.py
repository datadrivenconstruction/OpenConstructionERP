# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost item validation rules (rule set ``costs``).

Rules run over a plain dict context built by the caller. A single write sends one row,
a bulk import sends the whole batch, so a catalogue is checked in one pass::

    {"cost_items": [{"id", "code", "unit", "rate", "currency", "mass_per_unit",
                     "mass_basis", "components", "metadata"}]}
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.estimating_rules import EstimatingRule
from app.core.validation.money_rules import MAX_SANE_AMOUNT, MONEY_TOLERANCE, blank, rows, to_dec
from app.modules.costs.buildup import buildup_rate

COSTS_RULE_SET = "costs"

#: A built-up rate may differ from its components by this fraction before it is worth a second look.
ASSEMBLY_TOLERANCE = Decimal("0.01")


def _ref(row: dict) -> str:
    return str(row.get("code") or row.get("id") or "")


class CostRateInRangeRule(EstimatingRule):
    """A unit rate is a readable, non-negative number below the unit-slip ceiling."""

    rule_id = "costs.rate_in_range"
    name = "Cost item rate is sane"
    standard = COSTS_RULE_SET
    description = "rate must be a number between 0 and 1e12"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for row in rows(context, "cost_items"):
            rate = to_dec(row.get("rate"))
            ref = _ref(row)
            if rate is None:
                out.append(self.fail(context, "value_in_range", ref=ref, field="rate", value=row.get("rate"), low=0, high=MAX_SANE_AMOUNT))
                continue
            bad = self.out_of_range(context, ref, "rate", rate, Decimal("0"), MAX_SANE_AMOUNT)
            if bad:
                out.append(bad)
        return out or [self.ok()]


class CostMassPricingCompleteRule(EstimatingRule):
    """Pricing a section by mass needs both the basis (per tonne or per kg) and the kg per unit."""

    rule_id = "costs.mass_pricing_complete"
    name = "Mass-priced cost item is complete"
    standard = COSTS_RULE_SET
    description = "mass_basis requires a positive mass_per_unit, and mass_per_unit requires a mass_basis"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for row in rows(context, "cost_items"):
            basis = str(row.get("mass_basis") or "").strip().lower()
            mass = to_dec(row.get("mass_per_unit"))
            ref = _ref(row)
            if basis and (mass is None or mass <= 0):
                out.append(self.fail(context, "mass_basis_needs_mass", ref=ref, basis=basis))
            elif not basis and mass is not None and mass > 0:
                out.append(self.fail(context, "mass_needs_basis", ref=ref, mass=mass))
        return out or [self.ok()]


class CostCurrencyStatedRule(EstimatingRule):
    """A price is in some money: a priced item states its currency."""

    rule_id = "costs.currency_stated"
    name = "Cost item states its currency"
    standard = COSTS_RULE_SET
    severity = Severity.WARNING
    description = "a rate above zero requires a currency (own, catalogue or region)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "currency_present", ref=_ref(row))
            for row in rows(context, "cost_items")
            if (to_dec(row.get("rate")) or 0) > 0 and blank(row.get("currency"))
        ]
        return out or [self.ok()]


class CostAssemblyMatchesComponentsRule(EstimatingRule):
    """An assembly's rate agrees with the sum of its components."""

    rule_id = "costs.assembly_matches_components"
    name = "Assembly rate matches its components"
    standard = COSTS_RULE_SET
    severity = Severity.WARNING
    description = "rate should equal the sum of component costs (within 1%) unless the item is mass-priced or has variants"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for row in rows(context, "cost_items"):
            if str(row.get("mass_basis") or "").strip():
                continue
            rate = to_dec(row.get("rate"))
            expected = buildup_rate(row.get("components") or [], row.get("metadata") or {})
            if rate is None or expected is None or expected <= 0:
                continue
            bad = self.total_mismatch(
                context,
                _ref(row),
                "cost item",
                rate,
                expected,
                str(row.get("currency") or ""),
                max(MONEY_TOLERANCE, expected * ASSEMBLY_TOLERANCE),
            )
            if bad:
                out.append(bad)
        return out or [self.ok()]


COSTS_RULES = (
    CostRateInRangeRule,
    CostMassPricingCompleteRule,
    CostCurrencyStatedRule,
    CostAssemblyMatchesComponentsRule,
)


def register_costs_validation_rules() -> None:
    """Register the cost item rules with the platform rule registry."""
    for rule_class in COSTS_RULES:
        rule_registry.register(rule_class(), [COSTS_RULE_SET])


__all__ = ["COSTS_RULES", "COSTS_RULE_SET", "register_costs_validation_rules"]
