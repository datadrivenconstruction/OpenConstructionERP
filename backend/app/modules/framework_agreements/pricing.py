# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure pricing for framework agreements: period factor, effective rate, order net, cap use.

No database access here. Every figure an order freezes is built by these functions, and the
same step list is stored on the order line as ``metadata.rate_build`` so the screen can show
how a rate came about without recomputing it.

Rounding follows ``price_index.index_math``: money ROUND_HALF_UP at 2 dp, factors at 6 dp.

* R1 ``per_rate``: ``r_eff = round2(round2(base x F) x prod(multipliers)) + sum(add_per_unit)``,
  line = ``round2(qty x r_eff)``.
* R2 ``per_total``: ``net = round2(sum(round2(qty x round2(base x F))) x prod(multipliers))``,
  per group of lines that share one multiplier product.
* R3 factor: ``index_ratio`` = I(target) / I(base); ``formula`` = ``a + sum(w_i x I_i(t) / I_i(b))``.
* R4 before ``fixed_price_until`` the factor is exactly 1 by agreement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.price_index.index_math import (
    PeriodNotFoundError,
    period_for_date,
    quantize_factor,
    resolve_factor,
    to_decimal,
)

MONEY = Decimal("0.01")
PCT = Decimal("0.01")
ONE = Decimal("1")
ZERO = Decimal("0")

ESCALATION_METHODS = ("none", "index_ratio", "formula", "fixed_table")
ADJUSTMENT_KINDS = ("multiplier", "add_per_unit", "add_lump")
ADJUSTMENT_SCOPES = ("all", "flagged", "items", "group")
ROUNDING_MODES = ("per_rate", "per_total")
CAP_BASES = ("committed", "certified", "invoiced")


def round2(value: Decimal) -> Decimal:
    """Money rounding, 2 dp ROUND_HALF_UP."""
    return to_decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


class EscalationUnresolvedError(ValueError):
    """An index the period needs has no value for the base or target period (never a silent 1)."""

    def __init__(self, series: str, period: str) -> None:
        self.series = series
        self.period = period
        super().__init__(f"index {series!r} has no value for {period!r}")


@dataclass(frozen=True)
class FactorResult:
    """The period factor and how it was reached."""

    factor: Decimal
    method: str
    target_period: str
    fixed: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


def period_factor(
    *,
    method: str,
    ordered_at: date,
    base_period: str | None,
    fixed_price_until: date | None,
    series_refs: Sequence[Mapping[str, Any]],
    fixed_part: Decimal | None,
    index_points: Mapping[str, Mapping[str, Any]],
    fixed_factor: Decimal | None = None,
) -> FactorResult:
    """Return the factor a rate period applies to base rates for an order dated ``ordered_at``.

    Args:
        method: ``none`` | ``index_ratio`` | ``formula`` | ``fixed_table``.
        ordered_at: Order date; its month is the target period.
        base_period: ``YYYY-MM`` the base rates are expressed in.
        fixed_price_until: Before or on this date the factor is 1 (R4).
        series_refs: For ``index_ratio`` one ``{"series": name}``; for ``formula`` many
            ``{"series": name, "weight": w}``.
        fixed_part: The non-adjustable share ``a`` of a formula.
        index_points: ``{series_name: {"YYYY-MM": value}}``.
        fixed_factor: For ``fixed_table``, the factor stated by the agreement for this period.

    Raises:
        EscalationUnresolvedError: an index has no value for the base or target month.
        ValueError: weights of a formula do not sum to 1, or the method is unknown.
    """
    target = period_for_date(ordered_at)
    if fixed_price_until is not None and ordered_at <= fixed_price_until:
        return FactorResult(quantize_factor(ONE), method, target, fixed=True)
    if method == "none":
        return FactorResult(quantize_factor(ONE), method, target)
    if method == "fixed_table":
        return FactorResult(quantize_factor(fixed_factor if fixed_factor is not None else ONE), method, target)
    if not base_period:
        raise EscalationUnresolvedError("", "")
    if method == "index_ratio":
        name = str((series_refs[0] if series_refs else {}).get("series") or "")
        ratio = _ratio(name, index_points, base_period, target)
        return FactorResult(ratio, method, target, detail={"series": name, "base": base_period})
    if method == "formula":
        a = to_decimal(fixed_part or ZERO)
        total_weight = a
        factor = a
        parts: list[dict[str, str]] = []
        for ref in series_refs:
            name = str(ref.get("series") or "")
            weight = to_decimal(ref.get("weight") or ZERO)
            total_weight += weight
            ratio = _ratio(name, index_points, base_period, target)
            factor += weight * ratio
            parts.append({"series": name, "weight": str(weight), "ratio": str(ratio)})
        if total_weight != ONE:
            raise ValueError(f"formula weights sum to {total_weight}, not 1")
        return FactorResult(quantize_factor(factor), method, target, detail={"fixed_part": str(a), "parts": parts})
    raise ValueError(f"unknown escalation method {method!r}")


def _ratio(name: str, index_points: Mapping[str, Mapping[str, Any]], base: str, target: str) -> Decimal:
    points = index_points.get(name)
    if not points:
        raise EscalationUnresolvedError(name, target)
    try:
        return resolve_factor(points, base, target)
    except PeriodNotFoundError as exc:
        raise EscalationUnresolvedError(name, exc.period) from exc


@dataclass(frozen=True)
class AdjustmentSpec:
    """One condition adjustment of an agreement."""

    code: str
    kind: str
    value: Decimal
    scope: str = "all"
    scope_items: tuple[str, ...] = ()
    scope_group: str | None = None
    condition: str = ""


@dataclass(frozen=True)
class ItemSpec:
    """The part of an agreement item pricing needs."""

    code: str
    base_rate: Decimal
    surcharge_flags: tuple[str, ...] = ()
    escalation_group: str | None = None


def adjustment_applies(adj: AdjustmentSpec, item: ItemSpec, tags: Iterable[str]) -> bool:
    """Whether ``adj`` applies to ``item`` on an order carrying ``tags``."""
    tag_set = set(tags)
    if adj.condition and adj.condition not in tag_set:
        return False
    if adj.scope == "all":
        return True
    if adj.scope == "flagged":
        # An item is flagged for an adjustment by its code or by its condition tag.
        return adj.code in item.surcharge_flags or (bool(adj.condition) and adj.condition in item.surcharge_flags)
    if adj.scope == "items":
        return item.code in adj.scope_items
    if adj.scope == "group":
        return bool(adj.scope_group) and adj.scope_group == item.escalation_group
    return False


def unknown_condition_tags(tags: Iterable[str], adjustments: Iterable[AdjustmentSpec]) -> list[str]:
    """Condition tags on an order that no adjustment of the agreement names (``normal_hours`` is neutral)."""
    known = {a.condition for a in adjustments if a.condition}
    return [t for t in tags if t and t != "normal_hours" and t not in known]


@dataclass
class PricedLine:
    """One order line priced from the agreement."""

    code: str
    quantity: Decimal
    unit_rate: Decimal
    total: Decimal
    rate_build: dict[str, Any]


@dataclass
class PricedOrder:
    """All lines of an order and its net."""

    lines: list[PricedLine]
    net: Decimal
    rounding: str
    lump_sum: Decimal = ZERO


def _multiplier(adjs: Sequence[AdjustmentSpec]) -> Decimal:
    m = ONE
    for a in adjs:
        if a.kind == "multiplier":
            m *= to_decimal(a.value)
    return m


def effective_rate(
    base_rate: Decimal, factor: Decimal, adjs: Sequence[AdjustmentSpec]
) -> tuple[Decimal, dict[str, Any]]:
    """R1: the effective unit rate and its step-by-step build."""
    escalated = round2(to_decimal(base_rate) * factor)
    mult = _multiplier(adjs)
    adjusted = round2(escalated * mult)
    add = sum((to_decimal(a.value) for a in adjs if a.kind == "add_per_unit"), ZERO)
    r_eff = round2(adjusted + add)
    build = {
        "base_rate": str(round2(base_rate)),
        "period_factor": str(factor),
        "escalated_rate": str(escalated),
        "multipliers": [{"code": a.code, "value": str(a.value)} for a in adjs if a.kind == "multiplier"],
        "adjusted_rate": str(adjusted),
        "add_per_unit": [{"code": a.code, "value": str(a.value)} for a in adjs if a.kind == "add_per_unit"],
        "effective_rate": str(r_eff),
        "rounding": "per_rate",
    }
    return r_eff, build


def price_order(
    lines: Sequence[tuple[ItemSpec, Decimal]],
    *,
    factor: Decimal,
    adjustments: Sequence[AdjustmentSpec],
    tags: Iterable[str],
    rounding: str = "per_rate",
) -> PricedOrder:
    """Price an order's lines (R1 or R2) and add lump-sum adjustments once per order."""
    tag_list = list(tags)
    applicable = [[a for a in adjustments if adjustment_applies(a, item, tag_list)] for item, _ in lines]
    lump = round2(
        sum(
            (
                to_decimal(a.value)
                for a in adjustments
                if a.kind == "add_lump" and (not a.condition or a.condition in tag_list)
            ),
            ZERO,
        )
    )
    if rounding == "per_total":
        return _price_per_total(lines, factor, applicable, lump)
    priced: list[PricedLine] = []
    for (item, qty), adjs in zip(lines, applicable, strict=True):
        r_eff, build = effective_rate(item.base_rate, factor, adjs)
        total = round2(to_decimal(qty) * r_eff)
        priced.append(PricedLine(item.code, to_decimal(qty), r_eff, total, build))
    net = round2(sum((p.total for p in priced), ZERO) + lump)
    return PricedOrder(priced, net, "per_rate", lump)


def _price_per_total(
    lines: Sequence[tuple[ItemSpec, Decimal]],
    factor: Decimal,
    applicable: list[list[AdjustmentSpec]],
    lump: Decimal,
) -> PricedOrder:
    groups: dict[Decimal, Decimal] = {}
    base_lines: list[tuple[ItemSpec, Decimal, Decimal, Decimal, Decimal, list[AdjustmentSpec]]] = []
    for (item, qty), adjs in zip(lines, applicable, strict=True):
        rate = round2(to_decimal(item.base_rate) * factor)
        line_base = round2(to_decimal(qty) * rate)
        mult = _multiplier(adjs)
        add = sum((to_decimal(a.value) for a in adjs if a.kind == "add_per_unit"), ZERO)
        groups[mult] = groups.get(mult, ZERO) + line_base
        base_lines.append((item, to_decimal(qty), rate, line_base, mult, adjs))
        if add:
            groups[ONE] = groups.get(ONE, ZERO) + round2(to_decimal(qty) * add)
    net = round2(sum((round2(base * mult) for mult, base in groups.items()), ZERO) + lump)
    priced: list[PricedLine] = []
    for item, qty, rate, line_base, mult, adjs in base_lines:
        add = sum((to_decimal(a.value) for a in adjs if a.kind == "add_per_unit"), ZERO)
        total = round2(line_base * mult) + round2(qty * add)
        unit = round2(total / qty) if qty else rate
        build = {
            "base_rate": str(round2(item.base_rate)),
            "period_factor": str(factor),
            "escalated_rate": str(rate),
            "line_base": str(line_base),
            "multipliers": [{"code": a.code, "value": str(a.value)} for a in adjs if a.kind == "multiplier"],
            "add_per_unit": [{"code": a.code, "value": str(a.value)} for a in adjs if a.kind == "add_per_unit"],
            "rounding": "per_total",
        }
        priced.append(PricedLine(item.code, qty, unit, total, build))
    # The order net is the per-total figure; the cents it differs from the sum of rounded lines
    # go on the largest line, so the lines still add up to what the order says.
    diff = net - lump - sum((p.total for p in priced), ZERO)
    if diff and priced:
        biggest = max(priced, key=lambda p: p.total)
        biggest.total += diff
        biggest.rate_build["rounding_adjustment"] = str(diff)
    return PricedOrder(priced, net, "per_total", lump)


@dataclass(frozen=True)
class CapStatus:
    """Where an order leaves the agreement against its cap."""

    cap: Decimal | None
    prior: Decimal
    order: Decimal
    total_after: Decimal
    headroom_before: Decimal | None
    headroom_after: Decimal | None
    pct_after: Decimal | None
    exceeded: bool
    threshold_reached: bool


def cap_status(cap: Decimal | None, prior: Decimal, order: Decimal, threshold_pct: Decimal) -> CapStatus:
    """Test ``prior + order`` against ``cap`` (None or 0 means no cap)."""
    total = round2(to_decimal(prior) + to_decimal(order))
    if not cap or to_decimal(cap) <= 0:
        return CapStatus(None, round2(prior), round2(order), total, None, None, None, False, False)
    cap_d = to_decimal(cap)
    pct = (total / cap_d * 100).quantize(PCT, rounding=ROUND_HALF_UP)
    return CapStatus(
        cap=round2(cap_d),
        prior=round2(prior),
        order=round2(order),
        total_after=total,
        headroom_before=round2(cap_d - to_decimal(prior)),
        headroom_after=round2(cap_d - total),
        pct_after=pct,
        exceeded=total > cap_d,
        threshold_reached=pct >= to_decimal(threshold_pct),
    )


def term_months(start: date, end: date) -> int:
    """Whole months from ``start`` to the day after ``end`` (01.01.25-31.12.28 is 48)."""
    after = end + timedelta(days=1)
    months = (after.year - start.year) * 12 + (after.month - start.month)
    if after.day < start.day:
        months -= 1
    return months


def term_over_max(start: date, end: date, max_years: int) -> bool:
    """Whether the term runs longer than ``max_years``."""
    return term_months(start, end) > max_years * 12


def min_at_risk(
    min_value: Decimal | None, ordered: Decimal, start: date, end: date, today: date
) -> tuple[bool, int, Decimal]:
    """Whether ordering is behind a straight-line pace to the guaranteed minimum.

    At risk when at least half the term has passed and the share of the minimum ordered is below
    the share of the term elapsed. Returns ``(at_risk, days_left, pct_of_minimum_ordered)``.
    """
    if not min_value or to_decimal(min_value) <= 0 or end <= start:
        return False, 0, ZERO
    total_days = (end - start).days
    elapsed = max(0, min((today - start).days, total_days))
    days_left = max(0, (end - today).days)
    pct = (to_decimal(ordered) / to_decimal(min_value) * 100).quantize(PCT, rounding=ROUND_HALF_UP)
    elapsed_pct = Decimal(elapsed * 100) / Decimal(total_days)
    at_risk = elapsed_pct >= 50 and pct < 100 and pct < elapsed_pct
    return at_risk, days_left, pct
