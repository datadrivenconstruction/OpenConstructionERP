# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scan-vs-design rules (rule set ``pointcloud_deviation``).

Context, built by the scan-vs-design service::

    {"deviation": {"ref", "points_compared", "out_pct", "threshold_pct",
                   "tolerance_mm", "coverage_pct"}}

PCD-001 warning: the share of points outside the tolerance band is above the
    threshold the user set for this comparison (5 % when none is given, an
    advisory default that no standard sets).
PCD-002 warning: the scan covers under 80 % of the design area, so the
    statistics describe only part of it.
PCD-003 error: no scan point lies over the design: wrong surface or wrong
    coordinate system.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section
from app.modules.pointcloud.deviation import LOW_COVERAGE_PCT

DEVIATION_RULE_SET = "pointcloud_deviation"
#: Advisory share of out-of-tolerance points when the user sets none (UNSOURCED).
DEFAULT_OUT_THRESHOLD_PCT = 5.0


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _pct(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


class _DeviationRule(MoneyRule):
    standard = DEVIATION_RULE_SET
    message_section = "pointcloud"
    category = RuleCategory.CONSISTENCY


class OutOfToleranceShareRule(_DeviationRule):
    """PCD-001: most of the surface is built within tolerance."""

    rule_id = "PCD-001"
    name = "Share out of tolerance"
    severity = Severity.WARNING
    description = "Too many scan points lie outside the tolerance band of the design"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "deviation")
        out = _f(d.get("out_pct"))
        limit = _f(d.get("threshold_pct"))
        limit = DEFAULT_OUT_THRESHOLD_PCT if limit is None else limit
        if out is None or out <= limit:
            return [self.ok()]
        ref = str(d.get("ref") or "")
        return [
            self.fail(
                context,
                "out_of_tolerance",
                ref=ref,
                surface=ref,
                share=_pct(out),
                limit=_pct(limit),
                tol=_pct(_f(d.get("tolerance_mm")) or 0.0),
            )
        ]


class ScanCoverageRule(_DeviationRule):
    """PCD-002: the scan covers most of the design."""

    rule_id = "PCD-002"
    name = "Scan covers the design"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Statistics over a partly scanned design describe only the scanned part"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "deviation")
        cov = _f(d.get("coverage_pct"))
        if cov is None or not d.get("points_compared") or cov >= float(LOW_COVERAGE_PCT):
            return [self.ok()]
        ref = str(d.get("ref") or "")
        floor = _pct(float(LOW_COVERAGE_PCT))
        return [self.fail(context, "low_coverage", ref=ref, surface=ref, share=_pct(cov), floor=floor)]


class ScanOverDesignRule(_DeviationRule):
    """PCD-003: the scan and the design overlap at all."""

    rule_id = "PCD-003"
    name = "Scan over the design"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A comparison without a single point over the design means nothing"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "deviation")
        if d.get("points_compared") is None or int(d.get("points_compared") or 0) > 0:
            return [self.ok()]
        ref = str(d.get("ref") or "")
        return [self.fail(context, "no_overlap", ref=ref, surface=ref)]


DEVIATION_RULES = (OutOfToleranceShareRule, ScanCoverageRule, ScanOverDesignRule)


def register_deviation_rules() -> None:
    """Register the scan-vs-design rules with the platform rule registry."""
    for rule_class in DEVIATION_RULES:
        rule_registry.register(rule_class(), [DEVIATION_RULE_SET])


__all__ = ["DEFAULT_OUT_THRESHOLD_PCT", "DEVIATION_RULES", "DEVIATION_RULE_SET", "register_deviation_rules"]

register_deviation_rules()
