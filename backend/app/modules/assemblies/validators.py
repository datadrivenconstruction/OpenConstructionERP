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
from app.core.validation.money_rules import MoneyRule, currency_of, locale_of, rows, section, to_dec
from app.modules.assemblies.messages import translate as tax_translate

ASSEMBLIES_RULE_SET = "assemblies"
#: Component input-tax rules (TAX-001..006). They read ``tax`` on each component row, which the service
#: only supplies for a project that switched component tax on, so they stay silent everywhere else.
ASSEMBLIES_TAX_RULE_SET = "assemblies_tax"

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


class _TaxRule(MoneyRule):
    """Base of the component-tax rules: one finding per component row that has a tax profile."""

    standard = ASSEMBLIES_TAX_RULE_SET
    tax_key = ""

    def _finding(self, context: ValidationContext, comp: dict, **params: object) -> RuleResult:
        locale = locale_of(context)
        label = str(comp.get("description") or comp.get("id") or "")
        text_params = {"label": label, **params}
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=tax_translate(f"component_tax.{self.tax_key}.fail", locale=locale, **text_params),
            element_ref=str(comp.get("id") or ""),
            suggestion=tax_translate(f"component_tax.{self.tax_key}.suggestion", locale=locale),
            details={k: str(v) for k, v in text_params.items()},
        )

    def check(self, context: ValidationContext, comp: dict, tax: dict) -> RuleResult | None:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for comp in rows(context, "components"):
            tax = comp.get("tax")
            if not isinstance(tax, dict) or not tax.get("classified"):
                continue
            found = self.check(context, comp, tax)
            if found is not None:
                out.append(found)
        return out or [self.ok(_ref(context))]


class TaxRateValidRule(_TaxRule):
    """TAX-001: a stated rate lies in 0..100 and a stated tax code resolves to a rate."""

    rule_id = "assemblies.tax_001_rate_valid"
    name = "Tax rate is valid"
    description = "Rate between 0 and 100, tax code resolved"
    tax_key = "rate_invalid"

    def check(self, context: ValidationContext, comp: dict, tax: dict) -> RuleResult | None:
        raw = to_dec(tax.get("explicit_rate"))
        if raw is not None and not Decimal("0") <= raw <= Decimal("100"):
            return self._finding(context, comp, detail=f"{raw} %")
        if tax.get("code") and tax.get("reason") in ("unknown_code", "no_country", "unresolved", "invalid_rate"):
            return self._finding(context, comp, detail=f"{tax['code']} / {tax['reason']}")
        return None


class TaxableNeedsRateRule(_TaxRule):
    """TAX-002: a taxable component carries a rate or a tax code."""

    rule_id = "assemblies.tax_002_taxable_needs_rate"
    name = "Taxable component has a rate or code"
    description = "Taxable without rate and code is an error"
    tax_key = "taxable_without_rate"

    def check(self, context: ValidationContext, comp: dict, tax: dict) -> RuleResult | None:
        if tax.get("status") == "taxable" and tax.get("reason") == "no_rate":
            return self._finding(context, comp)
        return None


class ExemptWithRateRule(_TaxRule):
    """TAX-003: an exempt component states no positive rate."""

    rule_id = "assemblies.tax_003_exempt_with_rate"
    name = "Exempt component has no rate"
    severity = Severity.WARNING
    description = "Exempt with a rate above zero is flagged"
    tax_key = "exempt_with_rate"

    def check(self, context: ValidationContext, comp: dict, tax: dict) -> RuleResult | None:
        rate = to_dec(tax.get("explicit_rate"))
        if tax.get("status") == "exempt" and rate is not None and rate > 0:
            return self._finding(context, comp, rate=rate)
        return None


class InclusiveNeedsRateRule(_TaxRule):
    """TAX-004: a tax-inclusive price has a rate to take the tax out with."""

    rule_id = "assemblies.tax_004_inclusive_needs_rate"
    name = "Inclusive price has a rate"
    description = "A price that includes tax needs a rate"
    tax_key = "inclusive_without_rate"

    def check(self, context: ValidationContext, comp: dict, tax: dict) -> RuleResult | None:
        if tax.get("includes_tax") and tax.get("status") not in ("exempt", "out_of_scope") and tax.get("reason"):
            return self._finding(context, comp)
        return None


class MasterPriceDriftRule(_TaxRule):
    """TAX-005: an unapproved assembly still carries the master price it was built from."""

    rule_id = "assemblies.tax_005_master_price_drift"
    name = "Component follows the master price"
    severity = Severity.INFO
    description = "Unapproved assembly price differs from the master price"
    tax_key = "master_price_drift"

    def check(self, context: ValidationContext, comp: dict, tax: dict) -> RuleResult | None:
        if section(context, "assembly").get("approved"):
            return None
        master, own = to_dec(tax.get("master_price")), to_dec(tax.get("unit_cost"))
        if master is not None and own is not None and master != own:
            return self._finding(context, comp, unit_cost=own, master=master)
        return None


class RegistryRateInForceRule(_TaxRule):
    """TAX-006: the registry has a rate for the tax code on the pricing date."""

    rule_id = "assemblies.tax_006_rate_in_force"
    name = "Registry rate is in force"
    severity = Severity.WARNING
    description = "A tax code whose rate is not valid on the pricing date is flagged"
    tax_key = "rate_outside_validity"

    def check(self, context: ValidationContext, comp: dict, tax: dict) -> RuleResult | None:
        if tax.get("in_force") is False:
            return self._finding(context, comp, code=tax.get("code") or "", date=tax.get("on_date") or "")
        return None


ASSEMBLIES_TAX_RULES = (
    TaxRateValidRule,
    TaxableNeedsRateRule,
    ExemptWithRateRule,
    InclusiveNeedsRateRule,
    MasterPriceDriftRule,
    RegistryRateInForceRule,
)


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
    for rule_class in ASSEMBLIES_TAX_RULES:
        rule_registry.register(rule_class(), [ASSEMBLIES_TAX_RULE_SET])


__all__ = [
    "ASSEMBLIES_RULES",
    "ASSEMBLIES_RULE_SET",
    "ASSEMBLIES_TAX_RULES",
    "ASSEMBLIES_TAX_RULE_SET",
    "register_assemblies_validation_rules",
]
