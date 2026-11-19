# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surface build and staged volume rules (rule set ``survey_surfaces``).

Context, built by the service::

    {"surface": {"code", "used_all_classes", "missed_segments"},
     "stages": [{"material", "has_factors"}]}

SRV-080 warning: the point cloud had no class-2 ground points; all points used.
SRV-081 warning: some breakline segments could not be kept as triangle edges.
SRV-082 info: a staged material has no bank/loose/compacted factors.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, section

SURFACE_RULE_SET = "survey_surfaces"


class _SurfaceRule(MoneyRule):
    standard = SURFACE_RULE_SET
    message_section = "volumes"
    category = RuleCategory.CONSISTENCY


class GroundClassRule(_SurfaceRule):
    """SRV-080: a cloud surface is built from ground points."""

    rule_id = "SRV-080"
    name = "Ground class present"
    severity = Severity.WARNING
    description = "Without class-2 ground points, vegetation and machines end up in the surface"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s = section(context, "surface")
        if not s.get("used_all_classes"):
            return [self.ok()]
        code = str(s.get("code") or "")
        return [self.fail(context, "no_ground_class", ref=code, code=code)]


class BreaklinesKeptRule(_SurfaceRule):
    """SRV-081: every breakline segment is a triangle edge."""

    rule_id = "SRV-081"
    name = "Breaklines kept"
    severity = Severity.WARNING
    description = "A breakline segment that is not an edge lets triangles bridge the slope change"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s = section(context, "surface")
        missed = int(s.get("missed_segments") or 0)
        if missed <= 0:
            return [self.ok()]
        code = str(s.get("code") or "")
        return [self.fail(context, "breakline_missed", ref=code, code=code, n=str(missed))]


class StageFactorsRule(_SurfaceRule):
    """SRV-082: say when loose and compacted volumes cannot be shown."""

    rule_id = "SRV-082"
    name = "Material factors given"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "Bank, loose and compacted factors come from the user's table; core has none"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        missing = sorted(
            {str(r.get("material")) for r in rows(context, "stages") if r.get("material") and not r.get("has_factors")}
        )
        if not missing:
            return [self.ok()]
        return [self.fail(context, "no_factors", ref=m, material=m) for m in missing]


SURFACE_RULES = (GroundClassRule, BreaklinesKeptRule, StageFactorsRule)


def register_surface_validation_rules() -> None:
    """Register the surface rules with the platform rule registry."""
    for rule_class in SURFACE_RULES:
        rule_registry.register(rule_class(), [SURFACE_RULE_SET])


__all__ = ["SURFACE_RULES", "SURFACE_RULE_SET", "register_surface_validation_rules"]

register_surface_validation_rules()
