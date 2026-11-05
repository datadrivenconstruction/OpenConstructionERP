# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Takeoff measurement validation rules (rule set ``takeoff``).

Rules run over a plain dict context built by the caller::

    {"measurement": {"id", "type", "review_status", "measurement_value", "measurement_unit",
                     "volume", "points", "scale_pixels_per_unit", "linked_boq_position_id"}}

Only the quantity types (distance, polyline, area, volume, count) are judged; cloud, arrow,
text, rectangle and highlight are markup and carry no billed number.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.estimating_rules import MAX_MEASUREMENT, EstimatingRule
from app.core.validation.money_rules import blank, section, to_dec

TAKEOFF_RULE_SET = "takeoff"

#: Quantity type -> unit family it is measured in.
TYPE_FAMILY = {"distance": "length", "polyline": "length", "area": "area", "volume": "volume", "count": "count"}

#: Fewest vertices a drawn shape of the type needs to enclose or span anything.
MIN_POINTS = {"distance": 2, "polyline": 2, "area": 3, "volume": 3}

UNIT_FAMILY = {
    **dict.fromkeys(("m", "lm", "mm", "cm", "km", "ft", "in", "yd", "mi", "rm"), "length"),
    **dict.fromkeys(
        ("m2", "sqm", "sm", "mm2", "cm2", "km2", "ha", "sf", "sqft", "ft2", "yd2", "sy", "sqyd", "ac"), "area"
    ),
    **dict.fromkeys(("m3", "cum", "cbm", "l", "cf", "cuft", "ft3", "yd3", "cy", "cuyd"), "volume"),
    **dict.fromkeys(("pcs", "pc", "ea", "each", "nr", "no", "stk", "st", "unit", "units", "set", "ls"), "count"),
}


def unit_family(unit: object) -> str | None:
    """The family (length, area, volume, count) of a unit string, or ``None`` when it is not a known one."""
    text = str(unit or "").strip().lower().replace("²", "2").replace("³", "3").replace("^", "").replace(".", "")
    return UNIT_FAMILY.get(text.replace(" ", ""))


def _type_of(m: dict) -> str:
    return str(m.get("type") or "").strip().lower()


class TakeoffValueInRangeRule(EstimatingRule):
    """A measured quantity is non-negative and below the scale-slip ceiling."""

    rule_id = "takeoff.value_in_range"
    name = "Takeoff measurement is sane"
    standard = TAKEOFF_RULE_SET
    description = "measurement_value and volume must be between 0 and 10 million"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "measurement")
        ref = str(m.get("id", ""))
        if _type_of(m) not in TYPE_FAMILY:
            return [self.ok(ref)]
        out = [
            bad
            for field in ("measurement_value", "volume")
            if (
                bad := self.out_of_range(
                    context, ref, field, to_dec(m.get(field)), Decimal("0"), Decimal(MAX_MEASUREMENT)
                )
            )
        ]
        return out or [self.ok(ref)]


class TakeoffGeometryMatchesTypeRule(EstimatingRule):
    """A drawn shape has enough vertices for what it measures."""

    rule_id = "takeoff.geometry_matches_type"
    name = "Takeoff shape has enough points"
    standard = TAKEOFF_RULE_SET
    description = "a distance or polyline needs 2 points, an area or volume 3"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "measurement")
        ref = str(m.get("id", ""))
        mtype = _type_of(m)
        points = m.get("points") or []
        needed = MIN_POINTS.get(mtype)
        if needed is not None and 0 < len(points) < needed:
            return [
                self.fail(context, "geometry_too_few_points", ref=ref, type=mtype, count=len(points), needed=needed)
            ]
        return [self.ok(ref)]


class TakeoffLinkNeedsConfirmedRule(EstimatingRule):
    """A machine proposal reaches the bill of quantities only after a person confirmed it."""

    rule_id = "takeoff.link_needs_confirmed"
    name = "Only a confirmed measurement is linked to the BOQ"
    standard = TAKEOFF_RULE_SET
    description = "a proposed or rejected measurement cannot carry a BOQ position link"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "measurement")
        ref = str(m.get("id", ""))
        review = str(m.get("review_status") or "confirmed")
        if not blank(m.get("linked_boq_position_id")) and review in ("proposed", "rejected"):
            return [self.fail(context, "link_needs_confirmed", ref=ref, status=review)]
        return [self.ok(ref)]


class TakeoffScaleStatedRule(EstimatingRule):
    """A length, area or volume read off a drawing says which scale it was read at."""

    rule_id = "takeoff.scale_stated"
    name = "Takeoff measurement has a scale"
    standard = TAKEOFF_RULE_SET
    severity = Severity.WARNING
    description = "a drawn distance, polyline, area or volume needs scale_pixels_per_unit"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "measurement")
        ref = str(m.get("id", ""))
        mtype = _type_of(m)
        scale = to_dec(m.get("scale_pixels_per_unit"))
        if mtype in MIN_POINTS and len(m.get("points") or []) >= MIN_POINTS[mtype] and (scale is None or scale <= 0):
            return [self.fail(context, "scale_missing", ref=ref, type=mtype)]
        return [self.ok(ref)]


class TakeoffUnitMatchesTypeRule(EstimatingRule):
    """The unit belongs to the kind of quantity: metres for a distance, square metres for an area."""

    rule_id = "takeoff.unit_matches_type"
    name = "Takeoff unit fits the measurement type"
    standard = TAKEOFF_RULE_SET
    severity = Severity.WARNING
    description = "a distance is measured in a length unit, an area in an area unit, a volume in a volume unit"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "measurement")
        ref = str(m.get("id", ""))
        mtype = _type_of(m)
        family = unit_family(m.get("measurement_unit"))
        if mtype in TYPE_FAMILY and family is not None and family != TYPE_FAMILY[mtype]:
            return [self.fail(context, "unit_mismatch", ref=ref, type=mtype, unit=m.get("measurement_unit"))]
        return [self.ok(ref)]


TAKEOFF_RULES = (
    TakeoffValueInRangeRule,
    TakeoffGeometryMatchesTypeRule,
    TakeoffLinkNeedsConfirmedRule,
    TakeoffScaleStatedRule,
    TakeoffUnitMatchesTypeRule,
)


def register_takeoff_validation_rules() -> None:
    """Register the takeoff rules with the platform rule registry."""
    for rule_class in TAKEOFF_RULES:
        rule_registry.register(rule_class(), [TAKEOFF_RULE_SET])


__all__ = ["TAKEOFF_RULES", "TAKEOFF_RULE_SET", "register_takeoff_validation_rules"]
