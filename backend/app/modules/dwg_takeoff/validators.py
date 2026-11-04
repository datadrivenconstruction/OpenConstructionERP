# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DWG takeoff validation rules (rule set ``dwg_takeoff``).

Rules run over a plain dict context built by the caller::

    {
        "annotation": {"id", "annotation_type", "measurement_value", "measurement_unit",
                       "scale_override", "linked_boq_position_id"},
        "drawing": {"id", "scale_denominator", "scale_mode"},
    }

A drawing scale change sends ``drawing`` alone.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.estimating_rules import MAX_MEASUREMENT, EstimatingRule
from app.core.validation.money_rules import blank, section, to_dec

DWG_TAKEOFF_RULE_SET = "dwg_takeoff"

#: Annotation types that carry a measured length or area (a text pin or an arrow does not).
MEASURED_TYPES = frozenset({"distance", "area", "polyline", "line", "rectangle", "circle"})

#: Drawing scales 1:0.01 to 1:10000 cover enlarged details to site plans; beyond that the scale is a slip.
MIN_SCALE = Decimal("0.01")
MAX_SCALE = Decimal("10000")


class DwgMeasurementInRangeRule(EstimatingRule):
    """A measured quantity is non-negative and below the scale-slip ceiling."""

    rule_id = "dwg_takeoff.measurement_in_range"
    name = "DWG measurement is sane"
    standard = DWG_TAKEOFF_RULE_SET
    description = "measurement_value must be between 0 and 10 million"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        a = section(context, "annotation")
        ref = str(a.get("id", ""))
        bad = self.out_of_range(
            context, ref, "measurement_value", to_dec(a.get("measurement_value")), Decimal("0"), Decimal(MAX_MEASUREMENT)
        )
        return [bad] if bad else [self.ok(ref)]


class DwgCountIsWholeRule(EstimatingRule):
    """A count is a whole number: there are no 2.5 doors."""

    rule_id = "dwg_takeoff.count_is_whole"
    name = "DWG count is a whole number"
    standard = DWG_TAKEOFF_RULE_SET
    description = "a count annotation carries a whole, non-negative measurement_value"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        a = section(context, "annotation")
        ref = str(a.get("id", ""))
        value = to_dec(a.get("measurement_value"))
        if a.get("annotation_type") == "count" and value is not None and (value < 0 or value != value.to_integral_value()):
            return [self.fail(context, "count_not_whole", ref=ref, value=value)]
        return [self.ok(ref)]


class DwgUnitStatedRule(EstimatingRule):
    """A measured value states its unit, or it cannot be carried into a bill of quantities."""

    rule_id = "dwg_takeoff.unit_stated"
    name = "DWG measurement states its unit"
    standard = DWG_TAKEOFF_RULE_SET
    severity = Severity.WARNING
    description = "a measurement_value needs a measurement_unit"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        a = section(context, "annotation")
        ref = str(a.get("id", ""))
        if to_dec(a.get("measurement_value")) is not None and blank(a.get("measurement_unit")):
            return [self.fail(context, "field_required_for_state", ref=ref, state="measured", field="measurement_unit")]
        return [self.ok(ref)]


class DwgScalePlausibleRule(EstimatingRule):
    """The drawing scale is one a drawing can have."""

    rule_id = "dwg_takeoff.scale_plausible"
    name = "DWG scale is plausible"
    standard = DWG_TAKEOFF_RULE_SET
    severity = Severity.WARNING
    description = "scale_denominator between 0.01 and 10000"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "drawing")
        ref = str(d.get("id", ""))
        scale = to_dec(d.get("scale_denominator"))
        if scale is not None and not MIN_SCALE <= scale <= MAX_SCALE:
            return [self.fail(context, "scale_unusual", ref=ref, scale=scale)]
        return [self.ok(ref)]


class DwgScaleConfirmedRule(EstimatingRule):
    """A length or area is measured on a scale somebody chose, not on the untouched default."""

    rule_id = "dwg_takeoff.scale_confirmed"
    name = "DWG measurement uses a confirmed scale"
    standard = DWG_TAKEOFF_RULE_SET
    severity = Severity.WARNING
    description = "a measured length or area on a drawing still at the default 1:1 preset scale"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        a = section(context, "annotation")
        d = section(context, "drawing")
        ref = str(a.get("id", ""))
        measured = a.get("annotation_type") in MEASURED_TYPES and to_dec(a.get("measurement_value")) is not None
        untouched = to_dec(d.get("scale_denominator")) == 1 and str(d.get("scale_mode") or "preset") == "preset"
        if measured and untouched and to_dec(a.get("scale_override")) is None:
            return [self.fail(context, "scale_uncalibrated", ref=ref)]
        return [self.ok(ref)]


DWG_TAKEOFF_RULES = (
    DwgMeasurementInRangeRule,
    DwgCountIsWholeRule,
    DwgUnitStatedRule,
    DwgScalePlausibleRule,
    DwgScaleConfirmedRule,
)


def register_dwg_takeoff_validation_rules() -> None:
    """Register the DWG takeoff rules with the platform rule registry."""
    for rule_class in DWG_TAKEOFF_RULES:
        rule_registry.register(rule_class(), [DWG_TAKEOFF_RULE_SET])


__all__ = ["DWG_TAKEOFF_RULES", "DWG_TAKEOFF_RULE_SET", "register_dwg_takeoff_validation_rules"]
