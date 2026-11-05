# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Conceptual (ROM) estimate validation rules (rule set ``rom_estimate``).

Rules run over a plain dict context built by the service::

    {
        "estimate": {"id", "gfa_m2", "currency", "localized", "operation"},
        "project": {"saved_estimates", "boqs"},
    }

``operation`` is ``"save"`` for a saved baseline and ``"create_boq"`` when a
provisional bill is seeded from the estimate. Only the area can block: a gross
floor area outside any real building is a unit slip that would put a nonsense
total into the project baseline.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.cost_gate import raise_on_introduced, run_rule_set, warnings_of
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, currency_of, section, to_dec

ROM_ESTIMATE_RULE_SET = "rom_estimate"

#: Smallest and largest gross floor area, in m2, that is a building and not a unit slip.
GFA_LIMITS = (Decimal("1"), Decimal("10000000"))


class _RomRule(MoneyRule):
    standard = ROM_ESTIMATE_RULE_SET
    message_section = "rom_estimate"
    own_message_keys = frozenset({"region_not_set", "baseline_replaced", "boq_beside_detailed"})
    suggestion_key = "rom_estimate.suggestion"


def _ref(context: ValidationContext) -> str:
    return str(section(context, "estimate").get("id", ""))


class GrossFloorAreaRule(_RomRule):
    """The gross floor area is a real building, once converted to m2."""

    rule_id = "rom_estimate.area_in_range"
    name = "Gross floor area is plausible"
    description = "Gross floor area must be between 1 and 10,000,000 m2"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bad = self.out_of_range(
            context,
            _ref(context),
            "gross_floor_area (m2)",
            to_dec(section(context, "estimate").get("gfa_m2")),
            *GFA_LIMITS,
        )
        return [bad] if bad else [self.ok(_ref(context))]


class CurrencyStatedRule(_RomRule):
    """A total is an amount of something: the estimate states its currency."""

    rule_id = "rom_estimate.currency_stated"
    name = "Estimate currency stated"
    severity = Severity.WARNING
    description = "A saved baseline without a currency cannot be reconciled against the detailed bill"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        estimate = section(context, "estimate")
        if estimate and not currency_of(estimate):
            return [self.fail(context, "currency_present", ref=_ref(context))]
        return [self.ok(_ref(context))]


class RegionSetRule(_RomRule):
    """A regional cost factor is applied, otherwise the accuracy band stays wide."""

    rule_id = "rom_estimate.region_set"
    name = "Estimate region selected"
    severity = Severity.WARNING
    description = "With the worldwide default region no regional factor is applied"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        estimate = section(context, "estimate")
        if estimate and estimate.get("localized") is False:
            return [self.fail(context, "region_not_set", ref=_ref(context))]
        return [self.ok(_ref(context))]


class BaselineReplacedRule(_RomRule):
    """Saving a second concept estimate moves the project baseline."""

    rule_id = "rom_estimate.baseline_replaced"
    name = "New estimate replaces the baseline"
    severity = Severity.WARNING
    description = "The newest saved estimate is the one the detailed bill is reconciled against"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        saved = int(to_dec(section(context, "project").get("saved_estimates")) or 0)
        if saved > 0:
            return [self.fail(context, "baseline_replaced", ref=_ref(context), count=saved)]
        return [self.ok(_ref(context))]


class ConceptBoqBesideDetailedRule(_RomRule):
    """A concept bill seeded next to an existing bill counts the same building twice."""

    rule_id = "rom_estimate.boq_beside_detailed"
    name = "Concept bill beside an existing bill"
    severity = Severity.WARNING
    description = "Seeding a provisional bill into a project that already has bills double counts the scope"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        boqs = int(to_dec(section(context, "project").get("boqs")) or 0)
        if section(context, "estimate").get("operation") == "create_boq" and boqs > 0:
            return [self.fail(context, "boq_beside_detailed", ref=_ref(context), count=boqs)]
        return [self.ok(_ref(context))]


ROM_ESTIMATE_RULES = (
    GrossFloorAreaRule,
    CurrencyStatedRule,
    RegionSetRule,
    BaselineReplacedRule,
    ConceptBoqBesideDetailedRule,
)


def register_rom_estimate_validation_rules() -> None:
    """Register the ROM estimate rules with the platform rule registry."""
    for rule_class in ROM_ESTIMATE_RULES:
        rule_registry.register(rule_class(), [ROM_ESTIMATE_RULE_SET])


async def gate(context: dict, *, target_id: str) -> list[dict]:
    """Run the rule set at a write point: errors raise a coded 422, warnings are returned."""
    report = await run_rule_set(ROM_ESTIMATE_RULE_SET, context, target_type="rom_estimate", target_id=target_id)
    await raise_on_introduced(report, None, error="rom_estimate_rules_failed")
    return warnings_of(report)
