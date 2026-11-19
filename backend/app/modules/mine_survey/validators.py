# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey validation rules (rule set ``mine_survey``).

Rules run over one period entry, as a plain dict built by the service::

    {"entry": {"unit", "compliance_pct", "band_lo", "band_hi", "truck_factor_pct", "truck_tolerance_pct"}}

MIN-001 warning: period compliance is outside the band. There is no core band:
    it comes from the period profile, and without one the rule stays silent.
MIN-002 warning: truck-count tonnes differ from survey tonnes by more than the
    period's truck check; no tolerance, no judgement.
SRV-090 warning: material polygons leave part of the unit's actual unassigned.
SRV-091 warning: drive overbreak, or underbreak at some profiles, beyond the
    period's over/underbreak check (config; no core default).
SRV-092 error: a drive profile lies outside the drive's design chainage.
SRV-093 error: a blast hole's collar or depth is out of the pattern tolerance
    (rule set ``mine_blast``; tolerances are config, none in core).
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, section
from app.modules.mine_survey.calc import outside_band

MINE_RULE_SET = "mine_survey"
BLAST_RULE_SET = "mine_blast"
#: Rounding slack of grid cells along a polygon edge: below this the split counts as complete.
_FULL_COVERAGE_PCT = 99.5


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


class MaterialCoverageRule(_MineRule):
    """SRV-090: the material polygons cover the whole unit."""

    rule_id = "SRV-090"
    name = "Material polygons cover the unit"
    severity = Severity.WARNING
    description = "Volume outside every material polygon has no density of its own and no tonnes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        e = section(context, "entry")
        pct = _f(e.get("material_coverage_pct"))
        if pct is None or pct >= _FULL_COVERAGE_PCT:
            return [self.ok()]
        return [self.fail(context, "material_unassigned", ref=str(e.get("unit") or ""), p=_num(pct))]


class OverbreakRule(_MineRule):
    """SRV-091: the drive was excavated to its design section."""

    rule_id = "SRV-091"
    name = "Drive overbreak and underbreak within the check"
    severity = Severity.WARNING
    description = "Mean overbreak, or profiles smaller than the design, beyond the period's check"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "drive")
        tol, over = _f(d.get("tol_pct")), _f(d.get("overbreak_pct"))
        under = int(d.get("under_count") or 0)
        if tol is None or over is None or (over <= tol and under == 0):
            return [self.ok()]
        return [
            self.fail(context, "overbreak", ref=str(d.get("unit") or ""), o=_num(max(over, 0)), n=under, t=_num(tol))
        ]


class ProfileChainageRule(_MineRule):
    """SRV-092: every profile lies on the drive's design chainage."""

    rule_id = "SRV-092"
    name = "Profile on the design chainage"
    severity = Severity.ERROR
    description = "A profile outside the design chainage belongs to another drive or has a typing error"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "drive")
        out = [
            self.fail(context, "profile_outside", ref=str(d.get("unit") or ""), c=_num(float(c)))
            for c in d.get("outside") or []
        ]
        return out or [self.ok()]


class BlastHoleRule(_MineRule):
    """SRV-093: each drilled hole is where and as deep as designed."""

    rule_id = "SRV-093"
    name = "Blast hole collar and depth within tolerance"
    severity = Severity.ERROR
    description = "A hole off its collar or drilled short or deep changes burden, spacing and the blast result"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for h in rows(context, "holes"):
            if h.get("collar_ok") is False:
                out.append(
                    self.fail(
                        context,
                        "hole_collar",
                        ref=str(h.get("id") or ""),
                        id=h.get("id"),
                        v=h.get("collar_offset"),
                        t=h.get("collar_tol"),
                    )
                )
            if h.get("depth_ok") is False:
                out.append(
                    self.fail(
                        context,
                        "hole_depth",
                        ref=str(h.get("id") or ""),
                        id=h.get("id"),
                        v=h.get("depth_diff"),
                        t=h.get("depth_tol"),
                    )
                )
        return out or [self.ok()]


MINE_RULES = (ComplianceBandRule, TruckCountRule, MaterialCoverageRule, OverbreakRule, ProfileChainageRule)
BLAST_RULES = (BlastHoleRule,)


def register_mine_validation_rules() -> None:
    """Register the mine survey rules with the platform rule registry."""
    for rule_class in MINE_RULES:
        rule_registry.register(rule_class(), [MINE_RULE_SET])
    for rule_class in BLAST_RULES:
        rule_registry.register(rule_class(), [BLAST_RULE_SET])


__all__ = ["BLAST_RULES", "BLAST_RULE_SET", "MINE_RULES", "MINE_RULE_SET", "register_mine_validation_rules"]


# Registered at import so a process that only loads this module still knows the rule set.
register_mine_validation_rules()
