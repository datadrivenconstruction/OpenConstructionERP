# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey validation rules (rule set ``mine_survey``).

Rules run over one period entry, as a plain dict built by the service::

    {"entry": {"unit", "compliance_pct", "band_lo", "band_hi", "truck_factor_pct", "truck_tolerance_pct"}}

MIN-001 warning: period compliance is outside the band. There is no core band:
    it comes from the period profile, and without one the rule stays silent.
MIN-002 warning: truck-count tonnes differ from survey tonnes by more than the
    period's truck check; no tolerance, no judgement.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section
from app.modules.mine_survey.calc import outside_band

MINE_RULE_SET = "mine_survey"


class _MineRule(MoneyRule):
    standard = MINE_RULE_SET
    message_section = "mine_survey"
    category = RuleCategory.CONSISTENCY


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


class ComplianceBandRule(_MineRule):
    """MIN-001: the period delivered what the plan asked, within the band."""

    rule_id = "MIN-001"
    name = "Period compliance inside the band"
    severity = Severity.WARNING
    description = "Actual divided by plan outside the band means a plan miss or a survey that needs a second look"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        e = section(context, "entry")
        pct, lo, hi = _f(e.get("compliance_pct")), _f(e.get("band_lo")), _f(e.get("band_hi"))
        if not outside_band(pct, lo, hi):
            return [self.ok()]
        return [
            self.fail(
                context,
                "compliance_outside",
                ref=str(e.get("unit") or ""),
                c=_num(pct or 0),
                lo=_num(lo or 0),
                hi=_num(hi or 0),
            )
        ]


class TruckCountRule(_MineRule):
    """MIN-002: truck-count tonnes agree with survey tonnes."""

    rule_id = "MIN-002"
    name = "Truck count agrees with survey"
    severity = Severity.WARNING
    description = (
        "Loads times payload against surveyed volume times density; a gap points at payload, density or survey"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        e = section(context, "entry")
        pct, tol = _f(e.get("truck_factor_pct")), _f(e.get("truck_tolerance_pct"))
        if pct is None or tol is None or abs(pct) <= tol:
            return [self.ok()]
        return [self.fail(context, "truck_differs", ref=str(e.get("unit") or ""), v=_num(pct), t=_num(tol))]


MINE_RULES = (ComplianceBandRule, TruckCountRule)


def register_mine_validation_rules() -> None:
    """Register the mine survey rules with the platform rule registry."""
    for rule_class in MINE_RULES:
        rule_registry.register(rule_class(), [MINE_RULE_SET])


__all__ = ["MINE_RULES", "MINE_RULE_SET", "register_mine_validation_rules"]
