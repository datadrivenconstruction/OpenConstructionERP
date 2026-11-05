# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Price index validation rules (rule set ``price_index``).

Rules run over a plain dict context built by the service. Each rule reads only the
sections it knows and passes on any other write::

    {
        "point": {"id", "period"}, "points": [{"id", "period"}],            # one cost-index series
        "location": {"id", "region_code", "factor"}, "locations": [{"id", "region_code"}],
        "index": {"id", "source", "is_sample", "label"},                      # a resource index value
        "step": {"id", "label", "at", "value"}, "neighbours": [{"label", "at", "value"}],
    }

``at`` is an ISO year-month (``2026-03``) or a quarter (``2026-Q1``). Published
indices move slowly, so a jump between neighbours is more often a typing or unit
error than a market event; it is reported, not blocked.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.core.validation.cost_gate import raise_on_introduced, run_rule_set, warnings_of
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.failure import finding
from app.core.validation.money_rules import MoneyRule, blank, rows, section, to_dec

PRICE_INDEX_RULE_SET = "price_index"

#: Largest believable change between two neighbours, per month of distance.
MONTHLY_STEP_LIMIT = Decimal("1.1")
#: A regional factor outside this band around the national baseline of 1 is a slip, not a region.
LOCATION_FACTOR_BAND = (Decimal("0.5"), Decimal("2"))

_PERIOD = re.compile(r"^(\d{4})-(?:(\d{2})|Q([1-4]))$")


def month_number(at: object) -> int | None:
    """Months since year 0 for ``2026-03`` or ``2026-Q1`` (end of the quarter); ``None`` for anything else."""
    found = _PERIOD.match(str(at or "").strip())
    if not found:
        return None
    year, month, quarter = found.groups()
    return int(year) * 12 + (int(month) if month else int(quarter) * 3)


class _PriceIndexRule(MoneyRule):
    standard = PRICE_INDEX_RULE_SET
    message_section = "price_index"
    own_message_keys = frozenset(
        {"duplicate_key", "jump_implausible", "location_factor_outlier", "index_source_missing"}
    )
    suggestion_key = "price_index.suggestion"


class PeriodUniqueRule(_PriceIndexRule):
    """A series holds one value per period."""

    rule_id = "price_index.period_unique"
    name = "Index period is unique in its series"
    description = "Two points for one period make the index ambiguous"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        point = section(context, "point")
        ref = str(point.get("id", ""))
        period = str(point.get("period") or "").strip()
        if period and any(str(p.get("period") or "").strip() == period for p in rows(context, "points")):
            return [self.fail(context, "duplicate_key", ref=ref, what="period", value=period)]
        return [self.ok(ref)]


class RegionUniqueRule(_PriceIndexRule):
    """One location factor per region code."""

    rule_id = "price_index.region_unique"
    name = "Location factor region is unique"
    description = "Two factors for one region code make a regional conversion ambiguous"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = section(context, "location")
        ref = str(loc.get("id", ""))
        code = str(loc.get("region_code") or "").strip()
        if code and any(str(r.get("region_code") or "").strip() == code for r in rows(context, "locations")):
            return [self.fail(context, "duplicate_key", ref=ref, what="region code", value=code)]
        return [self.ok(ref)]


class LocationFactorBandRule(_PriceIndexRule):
    """A regional factor stays within a believable band around the national baseline."""

    rule_id = "price_index.location_factor_band"
    name = "Location factor is plausible"
    severity = Severity.WARNING
    description = "A regional factor below 0.5 or above 2 usually means a slipped decimal"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = section(context, "location")
        ref = str(loc.get("id", ""))
        value = to_dec(loc.get("factor"))
        low, high = LOCATION_FACTOR_BAND
        if value is not None and not low <= value <= high:
            return [
                self.fail(
                    context,
                    "location_factor_outlier",
                    ref=ref,
                    region=loc.get("region_code") or "",
                    factor=value,
                    low=low,
                    high=high,
                )
            ]
        return [self.ok(ref)]


class IndexStepPlausibleRule(_PriceIndexRule):
    """An index value does not leap away from its neighbouring periods."""

    rule_id = "price_index.step_plausible"
    name = "Index step between periods is plausible"
    severity = Severity.WARNING
    description = "More than 10 percent per month of distance from the nearest earlier or later value"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        step = section(context, "step")
        ref = str(step.get("id", ""))
        value, here = to_dec(step.get("value")), month_number(step.get("at"))
        if value is None or value <= 0 or here is None:
            return [self.ok(ref)]
        for other in rows(context, "neighbours"):
            there, base = month_number(other.get("at")), to_dec(other.get("value"))
            if there is None or base is None or base <= 0 or there == here:
                continue
            limit = MONTHLY_STEP_LIMIT ** abs(here - there)
            ratio = value / base
            if ratio > limit or ratio < 1 / limit:
                return [
                    self.fail(
                        context,
                        "jump_implausible",
                        ref=ref,
                        label=step.get("label") or step.get("at") or "",
                        value=value,
                        other_label=other.get("label") or other.get("at") or "",
                        other=base,
                        pct=((ratio - 1) * 100).quantize(Decimal("1")),
                    )
                ]
        return [self.ok(ref)]


class IndexSourceStatedRule(_PriceIndexRule):
    """An index entered by a person names the letter or release it comes from."""

    rule_id = "price_index.source_stated"
    name = "Index source stated"
    severity = Severity.WARNING
    description = "A resource index without a source cannot be checked against the published letter"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        index = section(context, "index")
        ref = str(index.get("id", ""))
        if index and not index.get("is_sample") and blank(index.get("source")):
            return [self.fail(context, "index_source_missing", ref=ref, label=index.get("label") or "")]
        return [self.ok(ref)]


PRICE_INDEX_RULES = (
    PeriodUniqueRule,
    RegionUniqueRule,
    LocationFactorBandRule,
    IndexStepPlausibleRule,
    IndexSourceStatedRule,
)


def register_price_index_validation_rules() -> None:
    """Register the price index rules with the platform rule registry."""
    for rule_class in PRICE_INDEX_RULES:
        rule_registry.register(rule_class(), [PRICE_INDEX_RULE_SET])


async def gate(
    context: dict[str, Any], before: dict[str, Any] | None, *, target_type: str, target_id: str
) -> list[dict[str, Any]]:
    """Run the rule set at a write point: errors the write introduces raise a coded 422, warnings are returned."""

    def run(payload: dict[str, Any]):
        return run_rule_set(PRICE_INDEX_RULE_SET, payload, target_type=target_type, target_id=target_id)

    report = await run(context)
    await raise_on_introduced(
        report, (lambda: run(before)) if before is not None else None, error="price_index_rules_failed"
    )
    return warnings_of(report)


def neighbours_of(points: list[tuple[str, Decimal]], at: str) -> list[dict[str, Any]]:
    """The nearest earlier and nearest later of ``points`` ``(period, value)`` around ``at``."""
    here = month_number(at)
    if here is None:
        return []
    dated = [(month_number(p), p, v) for p, v in points]
    earlier = max(((m, p, v) for m, p, v in dated if m is not None and m < here), default=None)
    later = min(((m, p, v) for m, p, v in dated if m is not None and m > here), default=None)
    return [{"label": p, "at": p, "value": v} for _, p, v in filter(None, (earlier, later))]


async def series_jump_warnings(
    series_name: str, points: dict[str, Decimal], *, locale: str = "en", limit: int = 50
) -> list[dict[str, Any]]:
    """Step findings along an imported series, one per period that leaps from its predecessor."""
    rule = IndexStepPlausibleRule()
    found: list[dict[str, Any]] = []
    ordered = sorted(points.items())
    for (prev_at, prev), (at, value) in zip(ordered, ordered[1:], strict=False):
        data = {
            "step": {"id": series_name, "label": f"{series_name} {at}", "at": at, "value": value},
            "neighbours": [{"label": f"{series_name} {prev_at}", "at": prev_at, "value": prev}],
        }
        for result in await rule.validate(ValidationContext(data=data, metadata={"locale": locale})):
            if not result.passed:
                found.append(finding(result))
        if len(found) >= limit:
            break
    return found
