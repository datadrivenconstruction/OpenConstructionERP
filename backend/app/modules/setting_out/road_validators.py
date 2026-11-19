# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the road and rail stake list (rule set ``setting_out_road``).

Rules run on one stake list as it is made::

    {"uncovered": [{"ref", "from", "to"}], "spirals_skipped": [{"ref", "element"}]}

SRV-070 error: the vertical profile does not cover a stretch of the stake list.
SRV-071 warning: a LandXML spiral without its length or radii was skipped.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows
from app.modules.setting_out.validators import SETTING_OUT_RULE_SET

ROAD_RULE_SET = "setting_out_road"


class _RoadRule(MoneyRule):
    standard = SETTING_OUT_RULE_SET
    message_section = "setting_out"
    category = RuleCategory.COMPLETENESS


def _ch(value: object) -> str:
    try:
        return f"{float(value):.3f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


class ProfileCoversRule(_RoadRule):
    """SRV-070: every staked chainage has a design level."""

    rule_id = "SRV-070"
    name = "Profile covers the stake list"
    severity = Severity.ERROR
    description = "Chainages of the stake list outside the vertical profile get no design level"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for u in rows(context, "uncovered"):
            a, b = _ch(u.get("from")), _ch(u.get("to"))
            out.append(
                self.fail(context, "profile_uncovered", ref=str(u.get("ref") or ""), c=a if a == b else f"{a}..{b}")
            )
        return out or [self.ok()]


class SpiralReadRule(_RoadRule):
    """SRV-071: a spiral element is read, never dropped silently."""

    rule_id = "SRV-071"
    name = "Spiral elements read"
    severity = Severity.WARNING
    description = "A LandXML spiral without length or radii is skipped and the alignment is shorter"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "spiral_skipped", ref=str(s.get("ref") or ""), n=str(s.get("element") or "?"))
            for s in rows(context, "spirals_skipped")
        ]
        return out or [self.ok()]


def register_road_validation_rules() -> None:
    for rule_class in (ProfileCoversRule, SpiralReadRule):
        rule_registry.register(rule_class(), [ROAD_RULE_SET])


__all__ = ["ROAD_RULE_SET", "register_road_validation_rules"]


register_road_validation_rules()
