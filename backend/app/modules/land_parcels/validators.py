# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels validation rules (rule set ``land_parcels``).

Rules run over a plain dict context built by the service::

    {
        "parcels": [{"id", "ref", "status", "legal_area", "computed_area", "closed", "ring",
                     "tolerance_m2", "tolerance_text", "id_valid", "id_label", "id_example"}],
        "work_zones": [{"id", "name", "ring"}],
        "settings": {"gap_tolerance_m"},
    }

The area tolerance is resolved per parcel by the service: the active pack's
formula when it has one, otherwise the project percentage. Rules only compare.

PAR-001 warning: computed area differs from the legal area beyond tolerance.
PAR-002 error: boundary ring not closed, too short or self-intersecting.
PAR-003 warning: the work zone overlaps a parcel that is not acquired.
PAR-004 error: two parcels overlap.
PAR-005 warning: a sliver gap between two neighbouring parcels.
PAR-006 warning: a parcel id that does not match the active pack's format.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, section, to_dec
from app.modules.land_parcels.geometry import (
    bboxes_apart,
    boundary_gap,
    intersection_area,
    open_ring,
    self_intersections,
)

PARCEL_RULE_SET = "land_parcels"
#: Overlaps below this are rounding noise of coordinates stored to 0.1 mm.
MIN_OVERLAP_M2 = 0.01


class _ParcelRule(MoneyRule):
    standard = PARCEL_RULE_SET
    message_section = "land_parcels"
    category = RuleCategory.CONSISTENCY


def _ring(p: dict) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in (p.get("ring") or [])]


def _valid(p: dict) -> bool:
    ring = _ring(p)
    return bool(p.get("closed", True)) and len(open_ring(ring)) >= 3 and not self_intersections(ring)


def _m2(value: float | Decimal) -> str:
    return f"{float(value):,.2f}"


class AreaMatchesLegalRule(_ParcelRule):
    """PAR-001: computed area agrees with the area in the register."""

    rule_id = "PAR-001"
    name = "Computed area matches legal area"
    severity = Severity.WARNING
    description = "Difference between the area from coordinates and the registered area, within tolerance"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for p in rows(context, "parcels"):
            legal, computed, tol = (
                to_dec(p.get("legal_area")),
                to_dec(p.get("computed_area")),
                to_dec(p.get("tolerance_m2")),
            )
            if legal is None or computed is None or tol is None:
                continue
            if abs(computed - legal) > tol:
                out.append(
                    self.fail(
                        context,
                        "area_mismatch",
                        ref=str(p.get("id") or ""),
                        id=str(p.get("ref") or ""),
                        a=_m2(computed),
                        l=_m2(legal),
                        t=str(p.get("tolerance_text") or _m2(tol)),
                    )
                )
        return out or [self.ok()]


class RingValidRule(_ParcelRule):
    """PAR-002: a parcel boundary is one closed ring that does not cross itself."""

    rule_id = "PAR-002"
    name = "Parcel ring closed and simple"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Ring not closed, fewer than three points, or edges that cross"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "ring_invalid", ref=str(p.get("id") or ""), id=str(p.get("ref") or ""))
            for p in rows(context, "parcels")
            if not _valid(p)
        ]
        return out or [self.ok()]


class WorkZoneAcquiredRule(_ParcelRule):
    """PAR-003: works do not enter land the project does not hold yet."""

    rule_id = "PAR-003"
    name = "Work zone only on acquired land"
    severity = Severity.WARNING
    description = "The work zone overlaps a parcel whose status is not Acquired"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        zones = [z for z in rows(context, "work_zones") if len(open_ring(_ring(z))) >= 3]
        out: list[RuleResult] = []
        for p in rows(context, "parcels"):
            if p.get("status") == "acquired" or not _valid(p):
                continue
            ring = _ring(p)
            overlap = sum(intersection_area(_ring(z), ring) for z in zones)
            if overlap >= MIN_OVERLAP_M2:
                out.append(
                    self.fail(
                        context,
                        "zone_not_acquired",
                        ref=str(p.get("id") or ""),
                        id=str(p.get("ref") or ""),
                        area=_m2(overlap),
                    )
                )
        return out or [self.ok()]


def _pairs(context: ValidationContext, margin: float) -> list[tuple[dict, dict]]:
    parcels = [p for p in rows(context, "parcels") if _valid(p)]
    return [
        (a, b) for i, a in enumerate(parcels) for b in parcels[i + 1 :] if not bboxes_apart(_ring(a), _ring(b), margin)
    ]


class NoOverlapRule(_ParcelRule):
    """PAR-004: two parcels never claim the same ground."""

    rule_id = "PAR-004"
    name = "Parcels do not overlap"
    severity = Severity.ERROR
    description = "Two parcels of the schedule share area"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for a, b in _pairs(context, 0.0):
            area = intersection_area(_ring(a), _ring(b))
            if area >= MIN_OVERLAP_M2:
                out.append(
                    self.fail(
                        context,
                        "overlap",
                        ref=str(a.get("id") or ""),
                        a=str(a.get("ref")),
                        b=str(b.get("ref")),
                        area=_m2(area),
                        other=str(b.get("id") or ""),
                    )  # fmt: skip
                )
        return out or [self.ok()]


class NoSliverGapRule(_ParcelRule):
    """PAR-005: neighbours meet on their shared boundary instead of leaving a sliver."""

    rule_id = "PAR-005"
    name = "No sliver gaps between neighbours"
    severity = Severity.WARNING
    description = "Two boundaries closer than the gap tolerance without touching"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        tol = float(to_dec(section(context, "settings").get("gap_tolerance_m")) or 0)
        if tol <= 0:
            return [self.ok()]
        out: list[RuleResult] = []
        for a, b in _pairs(context, tol):
            gap = boundary_gap(_ring(a), _ring(b))
            if 0 < gap <= tol and intersection_area(_ring(a), _ring(b)) < MIN_OVERLAP_M2:
                out.append(
                    self.fail(
                        context,
                        "gap",
                        ref=str(a.get("id") or ""),
                        a=str(a.get("ref")),
                        b=str(b.get("ref")),
                        gap=f"{gap:.3f}",
                        other=str(b.get("id") or ""),
                    )  # fmt: skip
                )
        return out or [self.ok()]


class ParcelIdFormatRule(_ParcelRule):
    """PAR-006: parcel ids follow the active pack's register format (only with a pack)."""

    rule_id = "PAR-006"
    name = "Parcel ID format"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Parcel ID does not match the format of the active country pack"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(
                context,
                "id_format",
                ref=str(p.get("id") or ""),
                id=str(p.get("ref") or ""),
                label=str(p.get("id_label") or ""),
                example=str(p.get("id_example") or ""),
            )  # fmt: skip
            for p in rows(context, "parcels")
            if p.get("id_valid") is False
        ]
        return out or [self.ok()]


PARCEL_RULES = (
    AreaMatchesLegalRule,
    RingValidRule,
    WorkZoneAcquiredRule,
    NoOverlapRule,
    NoSliverGapRule,
    ParcelIdFormatRule,
)


def register_parcel_validation_rules() -> None:
    """Register the parcel rules with the platform rule registry."""
    for rule_class in PARCEL_RULES:
        rule_registry.register(rule_class(), [PARCEL_RULE_SET])


__all__ = ["PARCEL_RULES", "PARCEL_RULE_SET", "register_parcel_validation_rules"]


# Registered at import so a process that only loads this module still knows the rule set.
register_parcel_validation_rules()
