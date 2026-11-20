# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the road and rail stake list (rule set ``setting_out_road``).

Rules run on one stake list as it is made::

    {"uncovered": [{"ref", "from", "to"}], "spirals_skipped": [{"ref", "element"}]}

SRV-070 error: the vertical profile does not cover a stretch of the stake list.
SRV-071 warning: a LandXML spiral without its length or radii was skipped.

The alignment editor sends ``{"curves": [{"ref", "radius", "min_radius", "speed"}],
"overlaps": [{"ref", "a", "b", "need", "have"}]}``:

SRV-072 warning: a curve radius is below the minimum for the design speed (pack or demo table).
SRV-073 error: two curves need more of a tangent than the tangent is long.
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


def _num(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _m(value: float) -> str:
    return f"{value:g}"


class MinRadiusRule(_RoadRule):
    """SRV-072: no curve is tighter than the minimum radius for the design speed."""

    rule_id = "SRV-072"
    name = "Minimum curve radius"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A horizontal curve radius below the minimum for the design speed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for c in rows(context, "curves"):
            r, rmin, v = _num(c.get("radius")), _num(c.get("min_radius")), _num(c.get("speed"))
            if r is None or rmin is None or r <= 0 or r >= rmin - 1e-9:
                continue
            ref = str(c.get("ref") or "")
            out.append(self.fail(context, "radius_below_min", ref=ref, ip=ref, r=_m(r), rmin=_m(rmin), v=_m(v or 0)))
        return out or [self.ok()]


class CurvesFitRule(_RoadRule):
    """SRV-073: curves on one tangent do not overlap."""

    rule_id = "SRV-073"
    name = "Curves fit between tangents"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The tangent lengths of neighbouring curves exceed the leg between their IPs"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for o in rows(context, "overlaps"):
            need, have = _num(o.get("need")) or 0.0, _num(o.get("have")) or 0.0
            out.append(
                self.fail(
                    context,
                    "curves_overlap",
                    ref=str(o.get("ref") or ""),
                    a=str(o.get("a") or ""),
                    b=str(o.get("b") or ""),
                    need=f"{need:.2f}",
                    have=f"{have:.2f}",
                )
            )
        return out or [self.ok()]


def register_road_validation_rules() -> None:
    for rule_class in (ProfileCoversRule, SpiralReadRule, MinRadiusRule, CurvesFitRule):
        rule_registry.register(rule_class(), [ROAD_RULE_SET])


__all__ = ["ROAD_RULE_SET", "register_road_validation_rules"]


register_road_validation_rules()
