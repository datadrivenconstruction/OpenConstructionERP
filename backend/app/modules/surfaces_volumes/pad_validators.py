# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design pad rule (rule set ``survey_surfaces``).

Context, built by the pad service or the plan editor::

    {"pad": {"name", "points", "self_intersections", "area_m2", "level_set", "unresolved"}}

SRV-083 error: the pad outline is a valid ring (three or more corners, no crossing
sides, an area) and the pad level is set.
SRV-083 warning: some batter corners never reached the ground surface.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section
from app.modules.surfaces_volumes.surface_validators import SURFACE_RULE_SET


class PadRingValidRule(MoneyRule):
    """SRV-083: a pad needs a closed, simple outline and a level."""

    rule_id = "SRV-083"
    name = "Pad ring valid"
    standard = SURFACE_RULE_SET
    message_section = "volumes"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    description = "A pad outline must close without crossing itself, and the pad needs a level"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pad = section(context, "pad")
        if not pad:
            return [self.ok()]
        name = str(pad.get("name") or "")
        out: list[RuleResult] = []
        if int(pad.get("points") or 0) < 3 or float(pad.get("area_m2") or 0) <= 0:
            out.append(self.fail(context, "pad_ring_open", ref=name, name=name))
        crossings = int(pad.get("self_intersections") or 0)
        if crossings:
            out.append(self.fail(context, "pad_self_intersects", ref=name, name=name, n=str(crossings)))
        if not pad.get("level_set"):
            out.append(self.fail(context, "pad_no_level", ref=name, name=name))
        unresolved = int(pad.get("unresolved") or 0)
        if unresolved:
            out.append(
                self.fail(context, "pad_batter_open", ref=name, name=name, n=str(unresolved), severity=Severity.WARNING)
            )
        return out or [self.ok()]


PAD_RULES = (PadRingValidRule,)


def register_pad_validation_rules() -> None:
    """Register SRV-083 with the platform rule registry."""
    for rule_class in PAD_RULES:
        rule_registry.register(rule_class(), [SURFACE_RULE_SET])


__all__ = ["PAD_RULES", "register_pad_validation_rules"]

register_pad_validation_rules()
