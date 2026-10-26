# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Condition rating and maintenance planning maths (pure, Decimal, no I/O).

Three questions, none of which needs the database:

* What rating does a recorded defect suggest? :func:`suggest_rating` maps
  severity, extent and intensity onto the levels of whatever scale is in use,
  with a confidence, so the inspector sees a proposal and sets the rating.
* Which maintenance actions follow from a rating? :func:`derive_actions` reads
  the action the scale attaches to that level (repair within N years, replace
  now, maintain every N years) and sizes it from the affected quantity.
* What does the plan cost per year? :func:`build_plan` expands one-off and
  recurring actions into year buckets over a horizon, inflates them by an
  annual rate (explicit, or derived from a cost index with
  :func:`annual_rate_from_points`) and discounts them to a present value with
  the whole-life-cost discounting the carbon module already uses.

The scale is data: a list of levels where level 1 is the best condition and the
last level the worst, each optionally carrying an ``action``. The core ships a
neutral six-level default; a country pack can bring its own scale and action
mapping without code.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.modules.carbon.lcc import net_present_value

__all__ = [
    "ACTION_TYPES",
    "annual_rate_from_points",
    "build_plan",
    "derive_actions",
    "extent_class",
    "inflate",
    "scale_level",
    "suggest_rating",
]

ACTION_TYPES = ("inspect", "maintain", "repair", "replace")

_MONEY = Decimal("0.01")
_ZERO = Decimal("0")
_ONE = Decimal("1")

#: Upper bounds (percent of the element affected) of the four extent classes.
_EXTENT_BOUNDS = (Decimal("10"), Decimal("30"), Decimal("60"))


def _dec(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    return d if d.is_finite() else default


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def extent_class(extent_pct: Any) -> int | None:
    """Extent as a class 1..4 (<10 %, 10-30 %, 30-60 %, >60 % of the element affected)."""
    pct = _dec(extent_pct)
    if pct is None or pct < 0:
        return None
    for idx, bound in enumerate(_EXTENT_BOUNDS, start=1):
        if pct < bound:
            return idx
    return 4


def suggest_rating(
    level_count: int,
    *,
    severity: int | None,
    extent_pct: Any = None,
    intensity: int | None = None,
) -> tuple[int | None, float]:
    """Propose a rating on a scale of ``level_count`` levels from a defect record.

    Severity (1 minor .. 4 critical) carries most of the weight, extent and
    intensity (1 low .. 4 high) adjust it. The weighted score (0..1) is spread
    over the scale's levels, level 1 being the best condition. A record without
    severity yields no proposal. Confidence grows with the number of inputs
    present and never claims certainty: the inspector decides.

    Returns:
        ``(level, confidence)``; ``(None, 0.0)`` when nothing can be proposed.
    """
    if level_count < 2 or severity is None or not 1 <= int(severity) <= 4:
        return None, 0.0
    parts = [(Decimal(int(severity) - 1) / 3, Decimal("0.6"))]
    ext = extent_class(extent_pct)
    if ext is not None:
        parts.append((Decimal(ext - 1) / 3, Decimal("0.25")))
    if intensity is not None and 1 <= int(intensity) <= 4:
        parts.append((Decimal(int(intensity) - 1) / 3, Decimal("0.15")))
    weight = sum(w for _, w in parts)
    score = sum(v * w for v, w in parts) / weight
    level = 1 + int((score * (level_count - 1)).quantize(_ONE, rounding=ROUND_HALF_UP))
    confidence = round(0.4 + 0.15 * (len(parts) - 1), 2)
    return max(1, min(level_count, level)), confidence


def scale_level(scale: Mapping[str, Any], rating: int) -> dict[str, Any] | None:
    """The level entry of a scale for a rating, or ``None`` when out of range."""
    for level in scale.get("levels") or []:
        if isinstance(level, Mapping) and int(level.get("level", -1)) == int(rating):
            return dict(level)
    return None


def derive_actions(
    assessment: Mapping[str, Any],
    scale: Mapping[str, Any],
    *,
    base_year: int,
) -> list[dict[str, Any]]:
    """Maintenance actions a rated assessment calls for, per the scale's mapping.

    The level's ``action`` gives ``type``, ``within_years`` (when the first
    occurrence is due), ``interval_years`` (recurring, optional) and
    ``priority``. Quantity is the element quantity times the affected extent
    for repairs (the whole quantity for a replacement when no extent is given),
    so a crack in a tenth of a facade is not priced as a new facade. High
    intensity (4) brings the due year forward one year, low intensity (1) lets
    it slip one year. Unit cost comes from the assessment; an action without
    one is still proposed and the validation rules ask for the price.

    Returns:
        Zero or one action dicts ready to persist as proposals.
    """
    rating = assessment.get("rating")
    if rating is None:
        return []
    level = scale_level(scale, int(rating))
    action = (level or {}).get("action")
    if not isinstance(action, Mapping) or action.get("type") not in ACTION_TYPES:
        return []

    within = int(action.get("within_years") or 0)
    intensity = assessment.get("intensity")
    if intensity is not None:
        if int(intensity) >= 4:
            within -= 1
        elif int(intensity) <= 1:
            within += 1
    within = max(0, within)
    interval = action.get("interval_years")
    interval_years = int(interval) if interval not in (None, "", 0) else None

    qty = _dec(assessment.get("quantity"))
    extent = _dec(assessment.get("extent_pct"))
    if qty is not None and extent is not None and action["type"] in ("repair", "replace"):
        qty = qty * max(_ZERO, min(Decimal("100"), extent)) / Decimal("100")
    unit_cost = _dec(assessment.get("unit_cost"))

    inputs = [assessment.get("severity"), extent, qty, unit_cost]
    confidence = round(min(0.9, 0.5 + 0.1 * sum(1 for v in inputs if v is not None)), 2)
    return [
        {
            "action_type": action["type"],
            "description": str(action.get("label") or action["type"]),
            "first_year": int(base_year) + within,
            "interval_years": interval_years,
            "quantity": format(qty.normalize(), "f") if qty is not None else None,
            "unit": assessment.get("unit"),
            "unit_cost": str(unit_cost) if unit_cost is not None else None,
            "priority": int(action.get("priority") or 3),
            "confidence": confidence,
        }
    ]


def annual_rate_from_points(points: Mapping[str, Any]) -> Decimal | None:
    """Compound annual growth of a cost index series of ``YYYY-MM`` points.

    Uses the first and last point by period; ``None`` when fewer than two
    usable points or less than one month apart.
    """
    usable: list[tuple[int, Decimal]] = []
    for key, raw in points.items():
        value = _dec(raw)
        if value is None or value <= 0 or not isinstance(key, str):
            continue
        try:
            year, month = key.strip()[:7].split("-")
            usable.append((int(year) * 12 + int(month) - 1, value))
        except ValueError:
            continue
    if len(usable) < 2:
        return None
    usable.sort()
    (m0, v0), (m1, v1) = usable[0], usable[-1]
    months = m1 - m0
    if months < 1:
        return None
    ratio = float(v1 / v0)
    rate = ratio ** (12.0 / months) - 1.0
    return Decimal(str(round(rate, 6)))


def inflate(amount: Decimal, rate: Decimal, years: int) -> Decimal:
    """``amount * (1 + rate) ** years`` (years < 0 treated as 0)."""
    n = max(0, int(years))
    if n == 0 or rate == 0:
        return amount
    return amount * ((_ONE + rate) ** n)


def _occurrences(first_year: int, interval: int | None, start: int, end: int) -> Iterable[int]:
    if interval is None or interval <= 0:
        if start <= first_year <= end:
            yield first_year
        elif first_year < start:
            # Overdue one-off work lands in the first plan year rather than vanishing.
            yield start
        return
    year = first_year
    if year < start:
        year += ((start - year + interval - 1) // interval) * interval
    while year <= end:
        yield year
        year += interval


def build_plan(
    actions: Iterable[Mapping[str, Any]],
    *,
    start_year: int,
    horizon_years: int,
    inflation_rate: Any = 0,
    discount_rate: Any = 0,
) -> dict[str, Any]:
    """Expand actions into year buckets with base, inflated and discounted cost.

    Args:
        actions: Dicts with ``id``, ``first_year``, ``interval_years``,
            ``quantity``, ``unit_cost`` and any display fields (copied through).
        start_year: First plan year (prices are taken at this year's level).
        horizon_years: Number of years in the plan (1..100).
        inflation_rate: Annual escalation applied from ``start_year``.
        discount_rate: Real discount rate for the present value.

    Returns:
        ``{"years": [{year, cost, cost_inflated, items: [...]}], "totals":
        {cost, cost_inflated, present_value, annual_equivalent, unpriced},
        "by_asset": {asset_ref: cost_inflated}}``; money as strings.
    """
    horizon = max(1, min(100, int(horizon_years)))
    end = start_year + horizon - 1
    rate = _dec(inflation_rate, _ZERO) or _ZERO
    disc = _dec(discount_rate, _ZERO) or _ZERO
    buckets: dict[int, dict[str, Any]] = {
        y: {"year": y, "cost": _ZERO, "cost_inflated": _ZERO, "items": []} for y in range(start_year, end + 1)
    }
    by_asset: dict[str, Decimal] = {}
    unpriced = 0
    present = _ZERO
    for action in actions:
        qty = _dec(action.get("quantity"), _ONE) or _ONE
        unit_cost = _dec(action.get("unit_cost"))
        if unit_cost is None:
            unpriced += 1
        base = _money(qty * unit_cost) if unit_cost is not None else _ZERO
        interval = action.get("interval_years")
        interval_i = int(interval) if interval not in (None, "", 0) else None
        for year in _occurrences(int(action.get("first_year") or start_year), interval_i, start_year, end):
            offset = year - start_year
            inflated = _money(inflate(base, rate, offset))
            bucket = buckets[year]
            bucket["cost"] += base
            bucket["cost_inflated"] += inflated
            bucket["items"].append({**dict(action), "year": year, "cost": str(base), "cost_inflated": str(inflated)})
            present += net_present_value(inflated, disc, offset)
            ref = str(action.get("asset_ref") or action.get("element_name") or "")
            if ref:
                by_asset[ref] = by_asset.get(ref, _ZERO) + inflated
    total = sum((b["cost"] for b in buckets.values()), _ZERO)
    total_inflated = sum((b["cost_inflated"] for b in buckets.values()), _ZERO)
    years = [
        {**b, "cost": str(_money(b["cost"])), "cost_inflated": str(_money(b["cost_inflated"]))}
        for b in sorted(buckets.values(), key=lambda b: b["year"])
    ]
    return {
        "start_year": start_year,
        "horizon_years": horizon,
        "inflation_rate": str(rate),
        "discount_rate": str(disc),
        "years": years,
        "totals": {
            "cost": str(_money(total)),
            "cost_inflated": str(_money(total_inflated)),
            "present_value": str(_money(present)),
            "annual_equivalent": str(_money(total_inflated / horizon)),
            "unpriced_actions": unpriced,
        },
        "by_asset": {k: str(_money(v)) for k, v in sorted(by_asset.items())},
    }
