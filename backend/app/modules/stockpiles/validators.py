# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile validation rules (rule set ``stockpiles``).

Rules run over one survey, as a plain dict built by the service::

    {"survey": {"code", "density_source", "variance_pct", "tolerance_pct"}}

STK-001 warning: the density is an assumption, not a measurement or a supplier value.
STK-002 warning: the survey differs from the book stock by more than the
    tolerance; 3 % when nothing says otherwise, an advisory default that no
    standard sets.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section
from app.modules.stockpiles.calc import DEFAULT_TOLERANCE_PCT

STOCKPILE_RULE_SET = "stockpiles"


class _StockpileRule(MoneyRule):
    standard = STOCKPILE_RULE_SET
    message_section = "stockpiles"
    category = RuleCategory.CONSISTENCY


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


class DensitySourceRule(_StockpileRule):
    """STK-001: tonnes rest on a density somebody assumed."""

    rule_id = "STK-001"
    name = "Density is measured or from the supplier"
    severity = Severity.WARNING
    description = "Tonnes are volume times density; an assumed density can move them by several percent"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s = section(context, "survey")
        if str(s.get("density_source") or "").strip().lower() != "assumed":
            return [self.ok()]
        return [self.fail(context, "density_assumed", ref=str(s.get("code") or ""))]


class BookVarianceRule(_StockpileRule):
    """STK-002: survey and book stock agree within the tolerance."""

    rule_id = "STK-002"
    name = "Survey agrees with book stock"
    severity = Severity.WARNING
    description = "A large gap between surveyed and book tonnes means a loss, a mis-booking or a wrong density"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s = section(context, "survey")
        pct = _f(s.get("variance_pct"))
        tol = _f(s.get("tolerance_pct"))
        tol = float(DEFAULT_TOLERANCE_PCT) if tol is None else tol
        if pct is None or abs(pct) <= tol:
            return [self.ok()]
        return [self.fail(context, "variance_high", ref=str(s.get("code") or ""), v=_num(pct), t=_num(tol))]


STOCKPILE_RULES = (DensitySourceRule, BookVarianceRule)


def register_stockpile_validation_rules() -> None:
    """Register the stockpile rules with the platform rule registry."""
    for rule_class in STOCKPILE_RULES:
        rule_registry.register(rule_class(), [STOCKPILE_RULE_SET])


__all__ = ["STOCKPILE_RULES", "STOCKPILE_RULE_SET", "register_stockpile_validation_rules"]
