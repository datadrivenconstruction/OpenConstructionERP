# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assembly validation rules (rule set ``assemblies``).

Rules run over a plain dict context built by the service::

    {
        "assembly": {"id", "code", "currency", "total_rate", "bid_factor", "operation"},
        "components": [{"id", "cost_item_id", "description", "factor", "quantity", "unit_cost"}],
    }

``operation`` is ``"edit"`` for a component or header write and ``"apply"``
when the assembly is about to be placed on a bill; only the apply gate
insists the assembly has something to price.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, currency_of, rows, section, to_dec

ASSEMBLIES_RULE_SET = "assemblies"

#: A waste, productivity or difficulty factor above this is a slipped decimal (1.15 typed as 115).
MAX_COMPONENT_FACTOR = Decimal("10")
#: Hard bounds of the bid factor, and the narrower band a real mark-up or discount stays in.
BID_FACTOR_LIMITS = (Decimal("0.1"), Decimal("10"))
BID_FACTOR_TYPICAL = (Decimal("0.5"), Decimal("2"))


class _AssemblyRule(MoneyRule):
    standard = ASSEMBLIES_RULE_SET
    message_section = "cost_rules"
    own_message_keys = frozenset({"duplicate_line", "empty_assembly"})


def _ref(context: ValidationContext) -> str:
    return str(section(context, "assembly").get("id", ""))


class ComponentFactorsRule(_AssemblyRule):
    """Component factors and the bid factor stay inside bounds a unit slip cannot reach."""

    rule_id = "assemblies.factors_in_range"
    name = "Assembly factors are in range"
    description = "Component factor 0 to 10; bid factor 0.1 to 10"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        out: list[RuleResult] = []
        for comp in rows(context, "components"):
            bad = self.out_of_range(
                context,
                str(comp.get("id") or ref),
                f"factor ({comp.get('description') or 'component'})",
                to_dec(comp.get("factor")),
                Decimal("0"),
                MAX_COMPONENT_FACTOR,
            )
            if bad:
                out.append(bad)
        bad = self.out_of_range(
            context, ref, "bid_factor", to_dec(section(context, "assembly").get("bid_factor")), *BID_FACTOR_LIMITS
        )
        if bad:
            out.append(bad)
        return out or [self.ok(ref)]


class BidFactorPlausibleRule(_AssemblyRule):
    """A bid factor beyond half to double the cost price is flagged for a second look."""

    rule_id = "assemblies.bid_factor_plausible"
    name = "Bid factor is plausible"
    severity = Severity.WARNING
    description = "Bid factors outside 0.5 to 2.0 are flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        value = to_dec(section(context, "assembly").get("bid_factor"))
        bad = self.out_of_range(context, ref, "bid_factor", value, *BID_FACTOR_TYPICAL)
        # Values beyond the hard limits are the error rule's to report.
        if bad and value is not None and BID_FACTOR_LIMITS[0] <= value <= BID_FACTOR_LIMITS[1]:
            return [bad]
        return [self.ok(ref)]


class DuplicateCostItemRule(_AssemblyRule):
    """The same cost item is not built into an assembly twice, which prices it twice."""

    rule_id = "assemblies.duplicate_cost_item"
    name = "No cost item used twice"
    severity = Severity.WARNING
    description = "Two components pointing at the same cost item are flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        seen: set[str] = set()
        out: list[RuleResult] = []
        for comp in rows(context, "components"):
            item = str(comp.get("cost_item_id") or "")
            if not item:
                continue
            if item in seen:
                out.append(
                    self.fail(
                        context,
                        "duplicate_line",
                        ref=str(comp.get("id") or ref),
                        label=str(comp.get("description") or item),
                    )
                )
            seen.add(item)
        return out or [self.ok(ref)]


class AssemblyCurrencyRule(_AssemblyRule):
    """An assembly that is priced states the currency it is priced in."""

    rule_id = "assemblies.currency_stated"
    name = "Assembly currency stated"
    severity = Severity.WARNING
    description = "A non-zero rate needs a currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        assembly = section(context, "assembly")
        ref = _ref(context)
        priced = (to_dec(assembly.get("total_rate")) or 0) > 0 or any(
            (to_dec(c.get("unit_cost")) or 0) > 0 for c in rows(context, "components")
        )
        if priced and not currency_of(assembly):
            return [self.fail(context, "currency_present", ref=ref)]
        return [self.ok(ref)]


class AssemblyApplicableRule(_AssemblyRule):
    """An assembly placed on a bill has components and a rate; otherwise the position prices at zero."""

    rule_id = "assemblies.applicable"
    name = "Assembly can be applied to a bill"
    description = "Applying an assembly with no components or a zero rate is refused"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        assembly = section(context, "assembly")
        ref = _ref(context)
        if assembly.get("operation") != "apply":
            return [self.ok(ref)]
        if not rows(context, "components") or not (to_dec(assembly.get("total_rate")) or 0) > 0:
            return [self.fail(context, "empty_assembly", ref=ref, code=assembly.get("code") or "")]
        return [self.ok(ref)]


ASSEMBLIES_RULES = (
    ComponentFactorsRule,
    BidFactorPlausibleRule,
    DuplicateCostItemRule,
    AssemblyCurrencyRule,
    AssemblyApplicableRule,
)


def register_assemblies_validation_rules() -> None:
    """Register the assembly rules with the platform rule registry."""
    for rule_class in ASSEMBLIES_RULES:
        rule_registry.register(rule_class(), [ASSEMBLIES_RULE_SET])


__all__ = ["ASSEMBLIES_RULES", "ASSEMBLIES_RULE_SET", "register_assemblies_validation_rules"]
