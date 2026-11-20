# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the survey calculations.

Rule set ``survey_calc`` runs on one computation as it is made::

    {"cogo": [{"ref", "method", "status": "parallel" | "two_solutions" | "ok"}]}

SRV-040 error: a bearing-bearing or line-line intersection of parallel lines.
SRV-041 warning: a distance-distance intersection with two solutions; the
person picks one before it is saved.

Rule set ``survey_core`` also gets two rules over stored traverses
(``traverses`` rows carry the extra keys below):

SRV-050 error: angular misclosure above ``k * sqrt(n)`` seconds
(``ang_misclosure_sec``, ``ang_k_sec``, ``angle_count``); no ``k``, no finding.
SRV-060 error: a level book whose arithmetic check fails
(``arithmetic_ok`` False, with ``sum_bs``, ``sum_fs``, ``first_rl``, ``last_rl``).

A least-squares traverse adds two rows to the ``survey_calc`` context::

    {"lsq": [{"ref", "vtpv", "lower", "upper", "redundancy", "sigma0"}],
     "lsq_residuals": [{"ref", "kind", "w"}]}

SRV-051 warning: the chi-square global test rejects the a priori weights.
SRV-052 warning: a standardized residual above Baarda's 3.29 (suspected blunder).
SRV-011 (level run within ``k * sqrt(km)``) also runs on a level book as it is computed.
"""

from __future__ import annotations

import math

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows
from app.modules.survey_core.validators import SURVEY_RULE_SET

SURVEY_CALC_RULE_SET = "survey_calc"


class _CalcRule(MoneyRule):
    standard = SURVEY_RULE_SET
    message_section = "survey"
    category = RuleCategory.CONSISTENCY


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class ParallelLinesRule(_CalcRule):
    """SRV-040: an intersection needs lines that are not parallel."""

    rule_id = "SRV-040"
    name = "Intersection lines are not parallel"
    severity = Severity.ERROR
    description = "Bearing-bearing or line-line intersection of two parallel lines has no answer"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "cogo_parallel", ref=str(c.get("ref") or ""))
            for c in rows(context, "cogo")
            if c.get("status") == "parallel"
        ]
        return out or [self.ok()]


class TwoSolutionsRule(_CalcRule):
    """SRV-041: a distance-distance intersection with two answers needs a choice."""

    rule_id = "SRV-041"
    name = "Distance-distance intersection resolved"
    severity = Severity.WARNING
    description = "Two circles meet twice; the surveyor picks the solution to keep"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "cogo_two_solutions", ref=str(c.get("ref") or ""))
            for c in rows(context, "cogo")
            if c.get("status") == "two_solutions"
        ]
        return out or [self.ok()]


class AngularMisclosureRule(_CalcRule):
    """SRV-050: a field traverse closes its angles within k * sqrt(n)."""

    rule_id = "SRV-050"
    name = "Angular misclosure within class"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Angular misclosure of a field traverse against k * sqrt(number of angles)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for t in rows(context, "traverses"):
            w, k, n = _f(t.get("ang_misclosure_sec")), _f(t.get("ang_k_sec")), _f(t.get("angle_count"))
            if w is None or not k or not n or abs(w) <= k * math.sqrt(n) + 1e-9:
                continue
            out.append(
                self.fail(
                    context,
                    "angular_misclosure",
                    ref=str(t.get("id") or ""),
                    a=f"{w:.1f}",
                    k=f"{k:g}",
                    n=f"{int(n)}",
                )
            )
        return out or [self.ok()]


class LevelArithmeticRule(_CalcRule):
    """SRV-060: sum BS - sum FS equals last RL - first RL."""

    rule_id = "SRV-060"
    name = "Level book arithmetic check"
    severity = Severity.ERROR
    description = "The book's sum of backsights minus foresights against the change in RL"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for t in rows(context, "traverses"):
            if t.get("kind") != "level" or t.get("arithmetic_ok") is not False:
                continue
            bs, fs = _f(t.get("sum_bs")) or 0.0, _f(t.get("sum_fs")) or 0.0
            first, last = _f(t.get("first_rl")) or 0.0, _f(t.get("last_rl")) or 0.0
            out.append(
                self.fail(
                    context,
                    "level_arithmetic",
                    ref=str(t.get("id") or ""),
                    name=str(t.get("name") or ""),
                    d=f"{bs - fs:.3f}",
                    r=f"{last - first:.3f}",
                )
            )
        return out or [self.ok()]


class LsqGlobalTestRule(_CalcRule):
    """SRV-051: the a posteriori variance factor passes the two-sided chi-square test."""

    rule_id = "SRV-051"
    name = "Least-squares global test"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Sum of weighted squared residuals inside the chi-square bounds for the redundancy"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for t in rows(context, "lsq"):
            vtpv, lo, hi = _f(t.get("vtpv")), _f(t.get("lower")), _f(t.get("upper"))
            if vtpv is None or lo is None or hi is None or lo <= vtpv <= hi:
                continue
            out.append(
                self.fail(
                    context,
                    "lsq_global_test",
                    ref=str(t.get("ref") or ""),
                    s=f"{_f(t.get('sigma0')) or 0.0:.2f}",
                    v=f"{vtpv:.2f}",
                    lo=f"{lo:.2f}",
                    hi=f"{hi:.2f}",
                )
            )
        return out or [self.ok()]


class LsqOutlierRule(_CalcRule):
    """SRV-052: no standardized residual above Baarda's critical value."""

    rule_id = "SRV-052"
    name = "Least-squares residual outlier"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Standardized residual above 3.29 marks an observation to check"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(
                context,
                "lsq_outlier",
                ref=str(r.get("ref") or ""),
                obs=str(r.get("ref") or ""),
                w=f"{_f(r.get('w')) or 0.0:.2f}",
            )
            for r in rows(context, "lsq_residuals")
        ]
        return out or [self.ok()]


CALC_RULES = (ParallelLinesRule, TwoSolutionsRule, LsqGlobalTestRule, LsqOutlierRule)
TRAVERSE_RULES = (AngularMisclosureRule, LevelArithmeticRule)


def register_calc_validation_rules() -> None:
    """Register the calculation rules: COGO in ``survey_calc``, closures in both sets."""
    for rule_class in CALC_RULES:
        rule_registry.register(rule_class(), [SURVEY_CALC_RULE_SET])
    for rule_class in TRAVERSE_RULES:
        rule_registry.register(rule_class(), [SURVEY_RULE_SET, SURVEY_CALC_RULE_SET])
    from app.modules.survey_core.validators import LevelRunRule  # noqa: PLC0415

    rule_registry.register(LevelRunRule(), [SURVEY_RULE_SET, SURVEY_CALC_RULE_SET])


__all__ = ["CALC_RULES", "SURVEY_CALC_RULE_SET", "TRAVERSE_RULES", "register_calc_validation_rules"]


register_calc_validation_rules()
