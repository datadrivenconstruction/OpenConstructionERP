# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Markup and scale validation rules (rule set ``markups``).

Rules run over a plain dict context built by the service::

    {
        "markup": {"id", "type", "measurement_value", "measurement_unit",
                   "operation", "has_scale"},
        "scale": {"id", "document_id", "unit_label"},
    }

``operation`` is ``"edit"`` for a create or update and ``"link"`` when the
markup is about to feed a bill position. ``has_scale`` is ``None`` when the
caller did not look a calibration up. A drawing markup without a measurement
(a cloud, an arrow, a stamp) is never judged here.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section, to_dec

MARKUPS_RULE_SET = "markups"

MEASURE_TYPES = frozenset({"distance", "area", "count"})
#: No drawing measures a billion of anything; this catches a pixel value stored as a quantity.
MAX_MEASUREMENT = Decimal("1e9")

_LENGTH = frozenset({"m", "mm", "cm", "km", "lm", "rm", "ft", "in", "yd", "mi", "lf"})
_AREA = frozenset({"m2", "sqm", "sq.m", "sqm.", "cm2", "mm2", "km2", "ha", "ft2", "sqft", "sq.ft", "sf", "yd2", "ac"})
_COUNT = frozenset({"pcs", "pc", "ea", "nr", "no", "each", "stk", "st", "item", "items", "unit", "units", "шт"})


def unit_class(unit: object) -> str | None:
    """``length``, ``area`` or ``count`` for a recognised unit, ``None`` for anything else."""
    text = re.sub(r"\s+", "", str(unit or "").casefold()).replace("²", "2")
    if text in _LENGTH:
        return "length"
    if text in _AREA:
        return "area"
    if text in _COUNT:
        return "count"
    return None


_EXPECTED = {"distance": "length", "area": "area", "count": "count"}


class _MarkupRule(MoneyRule):
    standard = MARKUPS_RULE_SET
    message_section = "cost_rules"
    own_message_keys = frozenset(
        {"unit_mismatch", "link_without_measurement", "scale_unit_not_length", "measurement_without_scale"}
    )


def _ref(context: ValidationContext) -> str:
    return str(section(context, "markup").get("id") or section(context, "scale").get("id") or "")


class MeasurementInRangeRule(_MarkupRule):
    """A measured quantity is not negative and not a pixel count in disguise."""

    rule_id = "markups.measurement_in_range"
    name = "Measurement is in a sane range"
    description = "Distance, area and count markups carry a value between 0 and 1e9"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        markup = section(context, "markup")
        ref = _ref(context)
        if markup.get("type") not in MEASURE_TYPES:
            return [self.ok(ref)]
        bad = self.out_of_range(
            context, ref, "measurement_value", to_dec(markup.get("measurement_value")), Decimal("0"), MAX_MEASUREMENT
        )
        return [bad] if bad else [self.ok(ref)]


class UnitMatchesTypeRule(_MarkupRule):
    """A distance is in a length unit, an area in an area unit, a count in pieces."""

    rule_id = "markups.unit_matches_type"
    name = "Measurement unit fits the markup type"
    description = "A distance in m2 or an area in m would put the wrong quantity on a bill"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        markup = section(context, "markup")
        ref = _ref(context)
        expected = _EXPECTED.get(str(markup.get("type")))
        found = unit_class(markup.get("measurement_unit"))
        # An unrecognised or missing unit is not judged: only a known-wrong one is a defect.
        if expected is None or found is None or found == expected:
            return [self.ok(ref)]
        return [self.fail(context, "unit_mismatch", ref=ref, unit=markup.get("measurement_unit"))]


class LinkNeedsMeasurementRule(_MarkupRule):
    """A markup linked to a bill position has a measured value to hand over."""

    rule_id = "markups.link_needs_measurement"
    name = "Linked markup carries a measurement"
    description = "Linking a markup with no measured value to a bill position is refused"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        markup = section(context, "markup")
        ref = _ref(context)
        if markup.get("operation") != "link":
            return [self.ok(ref)]
        value = to_dec(markup.get("measurement_value"))
        if value is None or value == 0:
            return [self.fail(context, "link_without_measurement", ref=ref)]
        return [self.ok(ref)]


class MeasurementHasScaleRule(_MarkupRule):
    """A drawn length or area sits on a page whose scale has been calibrated."""

    rule_id = "markups.measurement_has_scale"
    name = "Measured page has a calibrated scale"
    severity = Severity.WARNING
    description = "Distance and area values on a page with no scale calibration are unverified"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        markup = section(context, "markup")
        ref = _ref(context)
        if markup.get("type") not in {"distance", "area"} or markup.get("has_scale") is not False:
            return [self.ok(ref)]
        if (to_dec(markup.get("measurement_value")) or 0) == 0:
            return [self.ok(ref)]
        return [self.fail(context, "measurement_without_scale", ref=ref)]


class ScaleUnitIsLengthRule(_MarkupRule):
    """A scale is calibrated against a length, not an area or a piece count."""

    rule_id = "markups.scale_unit_is_length"
    name = "Scale is calibrated in a length unit"
    description = "A calibration reference is a known distance"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        scale = section(context, "scale")
        ref = _ref(context)
        found = unit_class(scale.get("unit_label"))
        if found in (None, "length"):
            return [self.ok(ref)]
        return [self.fail(context, "scale_unit_not_length", ref=ref, unit=scale.get("unit_label"))]


MARKUPS_RULES = (
    MeasurementInRangeRule,
    UnitMatchesTypeRule,
    LinkNeedsMeasurementRule,
    MeasurementHasScaleRule,
    ScaleUnitIsLengthRule,
)


def register_markups_validation_rules() -> None:
    """Register the markup rules with the platform rule registry."""
    for rule_class in MARKUPS_RULES:
        rule_registry.register(rule_class(), [MARKUPS_RULE_SET])


__all__ = ["MARKUPS_RULES", "MARKUPS_RULE_SET", "register_markups_validation_rules", "unit_class"]
