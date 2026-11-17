# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Volume validation rules (rule set ``surfaces_volumes``).

Rules run over one calculation, as a plain dict built by the service::

    {"volume": {"code", "coverage_pct", "coverage_min_pct", "accuracy_tier",
                "override_reason", "last_sent_quantity", "swell_factor"}}

VOL-001 error: the two surfaces hardly meet (under 1 % of the area).
VOL-002 warning: coverage below the profile minimum; 90 % when no profile
    says otherwise, an advisory default that no standard sets.
VOL-003 error: a coarse-tier scan feeds the result and nobody gave a reason.
VOL-004 info: the BOQ gets bank volume; the swell factor is not applied.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section
from app.modules.surfaces_volumes.volumes import is_coarse

VOLUME_RULE_SET = "surfaces_volumes"
#: Below this share of the area the surfaces are taken not to overlap at all.
MIN_OVERLAP_PCT = 1.0
#: Advisory coverage floor when no survey profile sets one (UNSOURCED).
DEFAULT_COVERAGE_MIN_PCT = 90.0


class _VolumeRule(MoneyRule):
    standard = VOLUME_RULE_SET
    message_section = "volumes"
    category = RuleCategory.CONSISTENCY


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _pct(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


class SurfacesOverlapRule(_VolumeRule):
    """VOL-001: base and compare share some ground."""

    rule_id = "VOL-001"
    name = "Surfaces overlap"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A volume between surfaces that do not overlap is meaningless"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        v = section(context, "volume")
        cov = _f(v.get("coverage_pct"))
        if cov is None or cov >= MIN_OVERLAP_PCT:
            return [self.ok()]
        return [self.fail(context, "no_overlap", ref=str(v.get("code") or ""), p=_pct(cov))]


class CoverageRule(_VolumeRule):
    """VOL-002: enough of the area has data in both surfaces."""

    rule_id = "VOL-002"
    name = "Coverage above minimum"
    severity = Severity.WARNING
    description = "Where one surface has no data the volume there is interpolated or missing"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        v = section(context, "volume")
        cov = _f(v.get("coverage_pct"))
        floor = _f(v.get("coverage_min_pct"))
        floor = DEFAULT_COVERAGE_MIN_PCT if floor is None else floor
        if cov is None or cov < MIN_OVERLAP_PCT or cov >= floor:
            return [self.ok()]
        return [self.fail(context, "low_coverage", ref=str(v.get("code") or ""), c=_pct(cov), min=_pct(floor))]


class CoarseScanRule(_VolumeRule):
    """VOL-003: a coarse-tier scan never feeds a BOQ quantity without a stated reason."""

    rule_id = "VOL-003"
    name = "No coarse scan without override"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Phone-grade scans (LOA10) are too coarse for a paid quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        v = section(context, "volume")
        if not is_coarse(v.get("accuracy_tier")) or str(v.get("override_reason") or "").strip():
            return [self.ok()]
        return [self.fail(context, "coarse_scan", ref=str(v.get("code") or ""))]


class BankVolumeRule(_VolumeRule):
    """VOL-004: say plainly that the quantity is bank volume."""

    rule_id = "VOL-004"
    name = "Bank volume to BOQ"
    severity = Severity.INFO
    description = "Cut and fill are in-ground volumes; loose volume needs the swell factor"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        v = section(context, "volume")
        if str(v.get("last_sent_quantity") or "") == "loose_cut":
            return [self.ok()]
        return [self.fail(context, "bank_volume", ref=str(v.get("code") or ""))]


VOLUME_RULES = (SurfacesOverlapRule, CoverageRule, CoarseScanRule, BankVolumeRule)


def register_volume_validation_rules() -> None:
    """Register the volume rules with the platform rule registry."""
    for rule_class in VOLUME_RULES:
        rule_registry.register(rule_class(), [VOLUME_RULE_SET])


__all__ = [
    "DEFAULT_COVERAGE_MIN_PCT",
    "VOLUME_RULES",
    "VOLUME_RULE_SET",
    "register_volume_validation_rules",
]
