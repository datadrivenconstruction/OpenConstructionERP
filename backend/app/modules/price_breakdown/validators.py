# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``price_breakdown``.

Payload::

    {"breakdowns": [{"position_ref", "unit_rate", "currency", "components": [...],
                     "overhead_pct", "risk_pct", "profit_pct"}]}

The rules read the raw values: the model clamps a bad markup silently, so the
only place a user hears about it is here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.price_breakdown.model import (
    MAX_MARKUP_PCT,
    PriceBreakdownError,
    _dec,
    build_breakdown,
    money_quantum,
)

PRICE_BREAKDOWN_RULE_SET = "price_breakdown"
_MARKUPS = ("overhead_pct", "risk_pct", "profit_pct")


def _breakdowns(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    return [r for r in (data.get("breakdowns") or []) if isinstance(r, dict)]


def _result(rule: ValidationRule, passed: bool, message: str, ref: str, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message="OK" if passed else message,
        element_ref=ref,
        details=details,
    )


def _in_range(value: Any) -> bool:
    try:
        pct = Decimal(str(value))
    except ArithmeticError:
        return False
    return Decimal("0") <= pct <= MAX_MARKUP_PCT


class ComponentsSumToRate(ValidationRule):
    """The stated unit rate equals the build-up of its components and markup."""

    rule_id = "price_breakdown.components_sum_to_rate"
    name = "Components Sum To Rate"
    standard = "price_breakdown"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A position's unit rate equals its resources plus overhead, risk and profit."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for row in _breakdowns(context):
            stated = row.get("unit_rate")
            if stated in (None, ""):
                continue
            ref = str(row.get("position_ref") or "")
            currency = str(row.get("currency") or "EUR")
            try:
                built = build_breakdown(
                    position_ref=ref,
                    description="",
                    unit="",
                    position_quantity=1,
                    components=list(row.get("components") or []),
                    overhead_pct=row.get("overhead_pct"),
                    risk_pct=row.get("risk_pct"),
                    profit_pct=row.get("profit_pct"),
                    currency=currency,
                )
            except PriceBreakdownError:
                out.append(_result(self, False, f"Position {ref} has a rate but no cost components", ref))
                continue
            computed = built.unit_rate
            diff = abs(computed - _dec(stated))
            out.append(
                _result(
                    self,
                    diff <= money_quantum(currency),
                    f"Position {ref} states a rate of {stated} but its components build up to {computed:.4f}",
                    ref,
                    stated=str(stated),
                    computed=str(computed),
                    difference=str(diff),
                )
            )
        return out


class MarkupInRange(ValidationRule):
    """Overhead, risk and profit are between 0 and the platform ceiling."""

    rule_id = "price_breakdown.markup_in_range"
    name = "Markup In Range"
    standard = "price_breakdown"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Markup percentages are not negative and do not exceed the platform maximum."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for row in _breakdowns(context):
            ref = str(row.get("position_ref") or "")
            bad = {k: str(row.get(k)) for k in _MARKUPS if row.get(k) not in (None, "") and not _in_range(row.get(k))}
            out.append(
                _result(
                    self,
                    not bad,
                    f"Position {ref} has a markup outside 0 to {MAX_MARKUP_PCT}%: "
                    + ", ".join(f"{k} {v}" for k, v in bad.items()),
                    ref,
                    **bad,
                )
            )
        return out


PRICE_BREAKDOWN_RULES = (ComponentsSumToRate, MarkupInRange)


def register_price_breakdown_rules() -> None:
    """Idempotently register the price breakdown rules."""
    for rule in PRICE_BREAKDOWN_RULES:
        rule_registry.register(rule(), rule_sets=[PRICE_BREAKDOWN_RULE_SET])


register_price_breakdown_rules()
