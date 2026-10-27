# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmark validation rules (rule set ``cost_benchmarks``).

* ``cost_benchmarks.element_outside_band`` - WARNING. An estimate element below P10 or above P90.
* ``cost_benchmarks.missing_quantity`` - ERROR. The estimate has no GFA (or no functional
  unit count when benchmarking per unit), so nothing can be compared.
* ``cost_benchmarks.low_confidence_cohort`` - WARNING. Fewer comparable projects than the
  stated minimum.
* ``cost_benchmarks.stale_indices`` - WARNING. The price index used is older than the
  stated number of months at the base date or the cost date.

The rules read the comparison returned by
:meth:`app.modules.cost_benchmarks.service.CostBenchmarksService.compare`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)

logger = logging.getLogger(__name__)

COST_BENCHMARKS_RULE_SET = "cost_benchmarks"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _result(rule: ValidationRule, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


class ElementOutsideBand(ValidationRule):
    rule_id = "cost_benchmarks.element_outside_band"
    name = "Estimate element outside the P10 to P90 band"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "An element of the estimate costs less than P10 or more than P90 of comparable projects."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for el in _data(context).get("elements") or []:
            if el.get("position") in ("below", "above"):
                band = el.get("band") or {}
                out.append(
                    _result(
                        self,
                        False,
                        f"Element {el.get('code')} is {el.get('estimate_per_unit')} per unit, "
                        f"{el.get('position')} the band {band.get('p10')} to {band.get('p90')}.",
                        el.get("code"),
                        position=el.get("position"),
                    )
                )
        return out or [_result(self, True, "OK")]


class MissingQuantity(ValidationRule):
    rule_id = "cost_benchmarks.missing_quantity"
    name = "Missing GFA or functional unit"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Cost per m2 or per unit needs the gross floor area or the functional unit count."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        est = data.get("estimate") or {}
        measure = data.get("measure") or "gfa"
        if measure == "gfa" and not est.get("gfa_m2"):
            return [_result(self, False, f"{est.get('name')} has no gross floor area.", est.get("name"))]
        if measure == "unit" and not (est.get("functional_unit") and est.get("functional_units")):
            return [_result(self, False, f"{est.get('name')} has no functional unit count.", est.get("name"))]
        return [_result(self, True, "OK")]


class LowConfidenceCohort(ValidationRule):
    rule_id = "cost_benchmarks.low_confidence_cohort"
    name = "Benchmark set with too few projects"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A band from fewer comparable projects than the minimum is a weak signal."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cohort = _data(context).get("cohort") or {}
        if cohort.get("low_confidence"):
            return [
                _result(
                    self,
                    False,
                    f"Only {cohort.get('count')} comparable projects, the minimum is {cohort.get('min_projects')}.",
                    count=cohort.get("count"),
                )
            ]
        return [_result(self, True, "OK")]


class StaleIndices(ValidationRule):
    rule_id = "cost_benchmarks.stale_indices"
    name = "Stale price indices"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The price index has no recent point near the base date or a project's cost date."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        basis = _data(context).get("basis") or {}
        if basis.get("stale"):
            return [
                _result(
                    self,
                    False,
                    f"Index '{basis.get('index_series') or 'none'}' ends at {basis.get('index_latest_period') or 'no point'}"
                    f", too far from the base date {basis.get('base_date')}.",
                )
            ]
        return [_result(self, True, "OK")]


_RULES: tuple[ValidationRule, ...] = (ElementOutsideBand(), MissingQuantity(), LowConfidenceCohort(), StaleIndices())
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_cost_benchmarks_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [COST_BENCHMARKS_RULE_SET])


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Failing results over a comparison."""
    register_cost_benchmarks_rules()
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[COST_BENCHMARKS_RULE_SET], target_type="cost_benchmark", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read
        logger.warning("cost benchmark validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]
