# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Preliminaries validation rules (rule set ``preliminaries``).

Rules run over a plain dict context built by the caller::

    {"item": {"id", "label", "category", "item_type", "rate_per_period", "periods", "fixed_amount"}}
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec

PRELIMINARIES_RULE_SET = "preliminaries"

#: Periods are weeks or months; beyond this the figure is a unit slip (days typed as weeks).
MAX_PERIODS = Decimal("1200")


def _amounts(item: dict) -> tuple[Decimal, Decimal, Decimal]:
    zero = Decimal("0")
    return (
        to_dec(item.get("rate_per_period")) or zero,
        to_dec(item.get("periods")) or zero,
        to_dec(item.get("fixed_amount")) or zero,
    )


class _PrelimRule(MoneyRule):
    standard = PRELIMINARIES_RULE_SET
    message_section = "preliminaries"
    own_message_keys = frozenset({"fixed_carries_rate", "timed_carries_fixed", "line_unpriced"})


class PrelimIgnoredAmountRule(_PrelimRule):
    """An amount entered on a line must be one the roll-up actually counts."""

    rule_id = "preliminaries.amount_counted"
    name = "Preliminaries amount is counted by the line type"
    description = "a fixed line prices only fixed_amount, a time-related line only rate x periods"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        rate, periods, fixed = _amounts(item)
        if item.get("item_type") == "fixed" and (rate > 0 or periods > 0):
            return [self.fail(context, "fixed_carries_rate", ref=ref)]
        if item.get("item_type") != "fixed" and fixed > 0:
            return [self.fail(context, "timed_carries_fixed", ref=ref)]
        return [self.ok(ref)]


class PrelimUnpricedRule(_PrelimRule):
    """A time-related line needs both a rate and a duration; a fixed line needs an amount."""

    rule_id = "preliminaries.line_priced"
    name = "Preliminaries line carries a price"
    severity = Severity.WARNING
    description = "a line that prices to nothing, or has only half of rate x periods, drops out of the total"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        rate, periods, fixed = _amounts(item)
        priced = fixed > 0 if item.get("item_type") == "fixed" else rate > 0 and periods > 0
        if not priced:
            return [self.fail(context, "line_unpriced", ref=ref)]
        return [self.ok(ref)]


class PrelimLabelRule(_PrelimRule):
    """A line that carries money says what it is for."""

    rule_id = "preliminaries.label_present"
    name = "Priced preliminaries line is named"
    description = "label is required once the line has a rate, a duration or an amount"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        if blank(item.get("label")) and any(v > 0 for v in _amounts(item)):
            return [self.fail(context, "reference_present", ref=ref, field="label")]
        return [self.ok(ref)]


class PrelimDurationRule(_PrelimRule):
    """The duration is a plausible number of weeks or months."""

    rule_id = "preliminaries.duration_sane"
    name = "Preliminaries duration is plausible"
    description = "periods must be between 0 and 1200"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        bad = self.out_of_range(context, ref, "periods", to_dec(item.get("periods")), Decimal("0"), MAX_PERIODS)
        return [bad] if bad else [self.ok(ref)]


PRELIMINARIES_RULES = (PrelimIgnoredAmountRule, PrelimUnpricedRule, PrelimLabelRule, PrelimDurationRule)


def register_preliminaries_validation_rules() -> None:
    """Register the preliminaries rules with the platform rule registry."""
    for rule_class in PRELIMINARIES_RULES:
        rule_registry.register(rule_class(), [PRELIMINARIES_RULE_SET])


__all__ = ["PRELIMINARIES_RULES", "PRELIMINARIES_RULE_SET", "register_preliminaries_validation_rules"]
