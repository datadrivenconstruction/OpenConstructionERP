# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register validation rules (rule set ``survey_core``).

Rules run over a plain dict context built by the service::

    {
        "crs": {"horizontal_epsg", "is_local_grid", "source", "detected_confidence", "confirmed"},
        "point_sets": [{"id", "name", "stored_epsg"}],
        "points": [{"point_id", "e", "n", "z", "set_id"}],
    }

SRV-001 error: a point set with no coordinate system.
SRV-002 warning: a detected project CRS nobody confirmed.
SRV-003 error: one point id with two different positions.
Traverse and level-run rules (SRV-010, SRV-011) come with the traverse slice;
their thresholds are pack profiles with no core default.
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


SURVEY_RULES = (PointSetHasCrsRule, CrsConfirmedRule, DuplicatePointRule)


def register_survey_validation_rules() -> None:
    """Register the survey register rules with the platform rule registry."""
    for rule_class in SURVEY_RULES:
        rule_registry.register(rule_class(), [SURVEY_RULE_SET])


__all__ = ["SURVEY_RULES", "SURVEY_RULE_SET", "register_survey_validation_rules"]
