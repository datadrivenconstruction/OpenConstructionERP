# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Basis-of-estimate validation rules (rule set ``estimate_basis``).

Rules run over a plain dict context built by the caller::

    {"basis": {"id", "status", "estimate_class", "accuracy_low_pct", "accuracy_high_pct",
              "market_conditions", "contingency_rationale", "budget_target", "pricing_date"}}

``metadata["today"]`` (ISO date) overrides the reference day for the pricing date check.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.estimating_rules import EstimatingRule
from app.core.validation.money_rules import MAX_SANE_AMOUNT, blank, section, to_dec
from app.core.validation.quality_rules import parse_day, today_of

ESTIMATE_BASIS_RULE_SET = "estimate_basis"

#: A rate base older than this is stale for a document that is being signed off.
PRICING_DATE_MAX_AGE = timedelta(days=365)


class BasisFinalNeedsClassRule(EstimatingRule):
    """A signed-off basis of estimate states the AACE class the estimator chose."""

    rule_id = "estimate_basis.final_needs_class"
    name = "Final basis of estimate states its class"
    standard = ESTIMATE_BASIS_RULE_SET
    description = "status final requires estimate_class 1-5"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        b = section(context, "basis")
        ref = str(b.get("id", ""))
        if b.get("status") == "final" and not b.get("estimate_class"):
            return [self.fail(context, "field_required_for_state", ref=ref, state="final", field="estimate_class")]
        return [self.ok(ref)]


class BasisAccuracyBandRule(EstimatingRule):
    """The accuracy band runs from a negative low to a positive high."""

    rule_id = "estimate_basis.accuracy_band"
    name = "Accuracy band brackets the estimate"
    standard = ESTIMATE_BASIS_RULE_SET
    description = "accuracy_low_pct must be 0 or below, accuracy_high_pct 0 or above"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        b = section(context, "basis")
        ref = str(b.get("id", ""))
        low, high = to_dec(b.get("accuracy_low_pct")), to_dec(b.get("accuracy_high_pct"))
        if (low is not None and low > 0) or (high is not None and high < 0):
            return [
                self.fail(
                    context,
                    "accuracy_band_invalid",
                    ref=ref,
                    low=low if low is not None else "",
                    high=high if high is not None else "",
                )
            ]
        return [self.ok(ref)]


class BasisBudgetTargetRule(EstimatingRule):
    """The client's budget target is a positive amount."""

    rule_id = "estimate_basis.budget_target_amount"
    name = "Budget target carries a positive amount"
    standard = ESTIMATE_BASIS_RULE_SET
    description = "a stated budget_target needs an amount between 0.01 and 1e12"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        b = section(context, "basis")
        ref = str(b.get("id", ""))
        target = b.get("budget_target")
        if not isinstance(target, dict) or not target:
            return [self.ok(ref)]
        if blank(target.get("amount")):
            return [self.ok(ref)]  # notes or currency entered first: a draft target without an amount yet
        amount = to_dec(target.get("amount"))
        if amount is None or not Decimal("0.01") <= amount <= MAX_SANE_AMOUNT:
            return [
                self.fail(
                    context,
                    "value_in_range",
                    ref=ref,
                    field="budget_target.amount",
                    value=target.get("amount") or "",
                    low="0.01",
                    high=MAX_SANE_AMOUNT,
                )
            ]
        return [self.ok(ref)]


class BasisFinalRationaleRule(EstimatingRule):
    """A signed-off basis says what the market was doing and why the contingency is what it is."""

    rule_id = "estimate_basis.final_rationale"
    name = "Final basis explains market and contingency"
    standard = ESTIMATE_BASIS_RULE_SET
    severity = Severity.WARNING
    description = "status final should carry market_conditions and contingency_rationale"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        b = section(context, "basis")
        ref = str(b.get("id", ""))
        if b.get("status") != "final":
            return [self.ok(ref)]
        out = [
            self.fail(context, "field_required_for_state", ref=ref, state="final", field=field)
            for field in ("market_conditions", "contingency_rationale")
            if blank(b.get(field))
        ]
        return out or [self.ok(ref)]


class BasisPricingDateCurrentRule(EstimatingRule):
    """A signed-off basis is priced on a rate base that is not a year old."""

    rule_id = "estimate_basis.pricing_date_current"
    name = "Final basis has a current pricing date"
    standard = ESTIMATE_BASIS_RULE_SET
    severity = Severity.WARNING
    description = "status final requires a pricing_date no older than 12 months"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        b = section(context, "basis")
        ref = str(b.get("id", ""))
        if b.get("status") != "final":
            return [self.ok(ref)]
        priced = parse_day(b.get("pricing_date"))
        if priced is None:
            return [self.fail(context, "field_required_for_state", ref=ref, state="final", field="pricing_date")]
        if today_of(context) - priced > PRICING_DATE_MAX_AGE:
            return [self.fail(context, "price_date_stale", ref=ref, date=priced.isoformat())]
        return [self.ok(ref)]


ESTIMATE_BASIS_RULES = (
    BasisFinalNeedsClassRule,
    BasisAccuracyBandRule,
    BasisBudgetTargetRule,
    BasisFinalRationaleRule,
    BasisPricingDateCurrentRule,
)


def register_estimate_basis_validation_rules() -> None:
    """Register the basis-of-estimate rules with the platform rule registry."""
    for rule_class in ESTIMATE_BASIS_RULES:
        rule_registry.register(rule_class(), [ESTIMATE_BASIS_RULE_SET])


__all__ = ["ESTIMATE_BASIS_RULES", "ESTIMATE_BASIS_RULE_SET", "register_estimate_basis_validation_rules"]
