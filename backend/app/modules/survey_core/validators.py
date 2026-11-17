# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register validation rules (rule set ``survey_core``).

Rules run over a plain dict context built by the service::

    {
        "crs": {"horizontal_epsg", "is_local_grid", "source", "detected_confidence", "confirmed"},
        "point_sets": [{"id", "name", "stored_epsg"}],
        "points": [{"point_id", "e", "n", "z", "set_id"}],
        "traverses": [{"id", "name", "kind", "ratio", "profile_ratio", "misclosure_mm", "allowed_mm", "k_mm"}],
    }

SRV-001 error: a point set with no coordinate system.
SRV-002 warning: a detected project CRS nobody confirmed.
SRV-003 error: one point id with two different positions.
SRV-010 error: a traverse closes worse than the profile's 1:x.
SRV-011 warning: a level run misses by more than k * sqrt(km).
Both thresholds come from a survey profile (pack, demo or the user's own);
there is no core default, so without a profile neither rule fires.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, section
from app.modules.survey_core.survey_math import same_position

SURVEY_RULE_SET = "survey_core"


class _SurveyRule(MoneyRule):
    standard = SURVEY_RULE_SET
    message_section = "survey"
    category = RuleCategory.CONSISTENCY


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class PointSetHasCrsRule(_SurveyRule):
    """SRV-001: every point set says which coordinate system it is in."""

    rule_id = "SRV-001"
    name = "Point sets have a coordinate system"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A point set without a CRS cannot feed volumes or parcels"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        crs = section(context, "crs")
        local = bool(crs.get("is_local_grid"))
        out = [
            self.fail(context, "no_crs", ref=str(s.get("id") or ""), name=str(s.get("name") or ""))
            for s in rows(context, "point_sets")
            if not s.get("stored_epsg") and not local
        ]
        return out or [self.ok()]


class CrsConfirmedRule(_SurveyRule):
    """SRV-002: a detected CRS is a suggestion until a person confirms it."""

    rule_id = "SRV-002"
    name = "Detected CRS confirmed"
    severity = Severity.WARNING
    description = "An auto-detected CRS is never applied without confirmation"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        crs = section(context, "crs")
        if crs.get("source") != "detected" or crs.get("confirmed"):
            return [self.ok()]
        conf = _f(crs.get("detected_confidence"))
        return [
            self.fail(
                context,
                "crs_unconfirmed",
                ref=str(crs.get("horizontal_epsg") or ""),
                confidence=f"{conf:.2f}" if conf is not None else "?",
            )
        ]


class DuplicatePointRule(_SurveyRule):
    """SRV-003: one point id names one position."""

    rule_id = "SRV-003"
    name = "No point id with two positions"
    severity = Severity.ERROR
    description = "The same point id with coordinates more than 1 mm apart"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        first: dict[str, tuple[float, float, float | None]] = {}
        flagged: list[str] = []
        for p in rows(context, "points"):
            pid = str(p.get("point_id") or "").strip()
            e, n = _f(p.get("e")), _f(p.get("n"))
            if not pid or e is None or n is None:
                continue
            pos = (e, n, _f(p.get("z")))
            seen = first.get(pid)
            if seen is None:
                first[pid] = pos
            elif pid not in flagged and not same_position(seen, pos):
                flagged.append(pid)
        out = [self.fail(context, "duplicate_point", ref=pid, point_id=pid) for pid in flagged]
        return out or [self.ok()]


class TraverseClosureRule(_SurveyRule):
    """SRV-010: a closed traverse meets the profile's minimum ratio."""

    rule_id = "SRV-010"
    name = "Traverse closes within profile"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Linear misclosure ratio 1:x against the profile's minimum"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for t in rows(context, "traverses"):
            if t.get("kind", "traverse") != "traverse":
                continue
            ratio, minimum = _f(t.get("ratio")), _f(t.get("profile_ratio"))
            if ratio is None or not minimum or ratio >= minimum:
                continue
            out.append(
                self.fail(
                    context,
                    "traverse_misclosure",
                    ref=str(t.get("id") or ""),
                    name=str(t.get("name") or ""),
                    r=f"{int(ratio):,}",
                    min=f"{int(minimum):,}",
                )
            )
        return out or [self.ok()]


class LevelRunRule(_SurveyRule):
    """SRV-011: a level run stays within k * sqrt(km)."""

    rule_id = "SRV-011"
    name = "Level run within allowance"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Level misclosure against k * sqrt(distance in km)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for t in rows(context, "traverses"):
            if t.get("kind") != "level":
                continue
            f, allowed, k = _f(t.get("misclosure_mm")), _f(t.get("allowed_mm")), _f(t.get("k_mm"))
            if f is None or allowed is None or not k or abs(f) <= allowed:
                continue
            out.append(self.fail(context, "level_misclosure", ref=str(t.get("id") or ""), f=f"{f:.1f}", k=f"{k:g}"))
        return out or [self.ok()]


SURVEY_RULES = (PointSetHasCrsRule, CrsConfirmedRule, DuplicatePointRule, TraverseClosureRule, LevelRunRule)


def register_survey_validation_rules() -> None:
    """Register the survey register rules with the platform rule registry."""
    for rule_class in SURVEY_RULES:
        rule_registry.register(rule_class(), [SURVEY_RULE_SET])


__all__ = ["SURVEY_RULES", "SURVEY_RULE_SET", "register_survey_validation_rules"]
