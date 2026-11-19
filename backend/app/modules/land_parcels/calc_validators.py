# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of parcel subdivision, corners and setbacks.

Rule set ``land_parcels_calc`` runs on one operation as it is made::

    {
        "subdivisions": [{"ref", "parent_area", "a", "b"}],
        "setbacks": [{"ref", "footprint", "boundary", "distance", "setback"}],
        "corners": [{"id", "label", "accuracy_m", "limit_m"}],
    }

SRV-100 error: the children areas do not add up to the parent area.
SRV-101 warning: a boundary corner whose stated precision exceeds its class
allowance (also in ``land_parcels``, over the stored corners).
SRV-102 warning: a footprint closer to a boundary edge than the setback.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows
from app.modules.land_parcels.validators import PARCEL_RULE_SET

PARCEL_CALC_RULE_SET = "land_parcels_calc"
#: Children may differ from the parent by rounding of the cut vertices only.
AREA_CLOSE_M2 = 0.01


class _CalcRule(MoneyRule):
    standard = PARCEL_RULE_SET
    message_section = "land_parcels"
    category = RuleCategory.CONSISTENCY


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class SubdivisionAreaRule(_CalcRule):
    """SRV-100: the parts of a split add up to the parent."""

    rule_id = "SRV-100"
    name = "Subdivision areas add up"
    severity = Severity.ERROR
    description = "The children of a split or the parents of a merge keep the total area"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for s in rows(context, "subdivisions"):
            p, a, b = _f(s.get("parent_area")), _f(s.get("a")), _f(s.get("b"))
            if p is None or a is None or b is None or abs(a + b - p) <= AREA_CLOSE_M2:
                continue
            out.append(
                self.fail(
                    context,
                    "subdivision_area",
                    ref=str(s.get("ref") or ""),
                    a=f"{a:,.2f}",
                    b=f"{b:,.2f}",
                    p=f"{p:,.2f}",
                    d=f"{a + b - p:,.2f}",
                )
            )
        return out or [self.ok()]


class CornerPrecisionRule(_CalcRule):
    """SRV-101: a corner's precision stays within its class allowance."""

    rule_id = "SRV-101"
    name = "Boundary corner precision within class"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Stated corner precision against the class base plus ppm of the distance to its neighbour"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for c in rows(context, "corners"):
            r, limit = _f(c.get("accuracy_m")), _f(c.get("limit_m"))
            if r is None or limit is None or r <= limit + 1e-9:
                continue
            out.append(
                self.fail(
                    context,
                    "corner_rpp",
                    ref=str(c.get("id") or ""),
                    id=str(c.get("label") or ""),
                    r=f"{r:.3f}",
                    limit=f"{limit:.3f}",
                )
            )
        return out or [self.ok()]


class SetbackRule(_CalcRule):
    """SRV-102: a footprint keeps the required distance from each boundary edge."""

    rule_id = "SRV-102"
    name = "Setback kept"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Minimum distance of a footprint to a boundary edge against the required setback"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for s in rows(context, "setbacks"):
            d, need = _f(s.get("distance")), _f(s.get("setback"))
            if d is None or need is None or d >= need - 1e-9:
                continue
            out.append(
                self.fail(
                    context,
                    "setback",
                    ref=str(s.get("ref") or ""),
                    f=str(s.get("footprint") or ""),
                    d=f"{d:.2f}",
                    b=str(s.get("boundary") or ""),
                    s=f"{need:.2f}",
                )
            )
        return out or [self.ok()]


def register_parcel_calc_validation_rules() -> None:
    """Register SRV-100/102 in ``land_parcels_calc`` and SRV-101 in both parcel sets."""
    rule_registry.register(SubdivisionAreaRule(), [PARCEL_CALC_RULE_SET])
    rule_registry.register(SetbackRule(), [PARCEL_CALC_RULE_SET])
    rule_registry.register(CornerPrecisionRule(), [PARCEL_RULE_SET, PARCEL_CALC_RULE_SET])


__all__ = ["PARCEL_CALC_RULE_SET", "register_parcel_calc_validation_rules"]


register_parcel_calc_validation_rules()
