# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the plan editor (rule set ``survey_core``).

Context key ``plan`` (built by :func:`plan_service.plan_context`)::

    {"library": [{code, line, ...}], "codes": ["EP1", "TR", ...], "sketch": [{id, geometry}]}

SRV-140 info: point codes the code library does not know (one finding per code, with a count).
SRV-141 warning: a coded string that cannot draw: one point, or a closed string with fewer than three.
SRV-142 warning: a drawn polygon with fewer than three distinct vertices.
SRV-143 error: a drawn polygon whose ring crosses itself.
SRV-144 warning: the project's code library lists a code twice.

The canvas runs the same checks live (``engine/liveChecks.ts``); this result is the record.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section
from app.modules.survey_core import plan_reference as ref
from app.modules.survey_core.validators import SURVEY_RULE_SET


class _PlanRule(MoneyRule):
    standard = SURVEY_RULE_SET
    message_section = "survey"
    category = RuleCategory.CONSISTENCY


def _plan(context: ValidationContext) -> dict[str, Any]:
    return section(context, "plan")


def _ring(geometry: Any) -> list[tuple[float, float]] | None:
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        return None
    try:
        ring = [(float(p[0]), float(p[1])) for p in (geometry.get("coordinates") or [[]])[0]]
    except (TypeError, ValueError, IndexError):
        return []
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    out: list[tuple[float, float]] = []
    for p in ring:
        if not out or out[-1] != p:
            out.append(p)
    return out


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def ring_crossings(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Proper crossings of non-adjacent edges of a closed ring."""
    n = len(ring)
    out: list[tuple[float, float]] = []
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            c, d = ring[j], ring[(j + 1) % n]
            d1, d2 = _cross(c, d, a), _cross(c, d, b)
            d3, d4 = _cross(a, b, c), _cross(a, b, d)
            if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
                t = d1 / (d1 - d2)
                out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return out


class CodeUnknownRule(_PlanRule):
    """SRV-140: a point code is not in the code library."""

    rule_id = "SRV-140"
    name = "Point codes are in the code library"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "A code the library does not know draws no symbol and no linework"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = _plan(context)
        library = list(plan.get("library") or [])
        if not library:
            return [self.ok()]
        unknown = ref.unknown_codes([str(c or "") for c in plan.get("codes") or []], library)
        return [self.fail(context, "code_unknown", ref=code, code=code, count=n) for code, n in unknown.items()] or [
            self.ok()
        ]


class StringShortRule(_PlanRule):
    """SRV-141: a coded string has too few points to draw."""

    rule_id = "SRV-141"
    name = "Coded strings have enough points"
    severity = Severity.WARNING
    description = "One point is no line; a closed string needs three"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = _plan(context)
        library = list(plan.get("library") or [])
        out = [
            self.fail(
                context,
                "string_short_closed" if s["closed"] else "string_short",
                ref=s["key"],
                name=s["key"],
                count=s["count"],
            )
            for s in ref.short_strings([str(c or "") for c in plan.get("codes") or []], library)
        ]
        return out or [self.ok()]


class RingOpenRule(_PlanRule):
    """SRV-142: a drawn polygon has fewer than three distinct vertices."""

    rule_id = "SRV-142"
    name = "Drawn polygons have three vertices"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A polygon with fewer than three distinct vertices has no area"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for f in _plan(context).get("sketch") or []:
            ring = _ring(f.get("geometry"))
            if ring is not None and len(ring) < 3:
                out.append(self.fail(context, "ring_open", ref=str(f.get("id") or "")))
        return out or [self.ok()]


class RingCrossesRule(_PlanRule):
    """SRV-143: a drawn polygon crosses itself."""

    rule_id = "SRV-143"
    name = "Drawn polygons do not cross themselves"
    severity = Severity.ERROR
    description = "A self-crossing ring has no meaningful area"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for f in _plan(context).get("sketch") or []:
            ring = _ring(f.get("geometry"))
            if not ring or len(ring) < 4:
                continue
            hits = ring_crossings(ring)
            if hits:
                e, n = hits[0]
                out.append(self.fail(context, "ring_crosses", ref=str(f.get("id") or ""), e=f"{e:.3f}", n=f"{n:.3f}"))
        return out or [self.ok()]


class CodeDuplicateRule(_PlanRule):
    """SRV-144: the code library lists a code twice."""

    rule_id = "SRV-144"
    name = "Code library has unique codes"
    severity = Severity.WARNING
    description = "Two entries for one code make symbols and linework ambiguous"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        dups = ref.duplicate_codes(list(_plan(context).get("library") or []))
        return [self.fail(context, "code_duplicate", ref=c, code=c) for c in dups] or [self.ok()]


PLAN_RULES = (CodeUnknownRule, StringShortRule, RingOpenRule, RingCrossesRule, CodeDuplicateRule)


def register_plan_validation_rules() -> None:
    """Register the plan rules with the platform rule registry."""
    for rule_class in PLAN_RULES:
        rule_registry.register(rule_class(), [SURVEY_RULE_SET])


__all__ = ["PLAN_RULES", "register_plan_validation_rules", "ring_crossings"]

register_plan_validation_rules()
