# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure capital-plan arithmetic: phasing, yearly summary, greedy funding, scenario compare.

No database and no framework imports, so every function is unit-testable on its own.
Items are plain dicts: ``id, project_id, title, priority, start_year, duration_years,
total_cost, phasing, status, score``. Money is ``Decimal`` rounded to cents.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
#: Statuses that draw on the envelope; a deferred item is parked and costs nothing.
ACTIVE_STATUSES = ("proposed", "funded")


def money(value: Any) -> Decimal:
    """Coerce to a Decimal rounded to cents; junk becomes zero."""
    try:
        return Decimal(str(value if value is not None else "0")).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def even_phasing(duration: int) -> list[Decimal]:
    """Equal fractions over ``duration`` years (the default when no phasing is given)."""
    n = max(int(duration), 1)
    return [Decimal(1) / Decimal(n)] * n


def phasing_fractions(item: dict[str, Any]) -> list[Decimal]:
    """The stored fractions, or the even split when none are stored."""
    raw = item.get("phasing") or []
    if not raw:
        return even_phasing(int(item.get("duration_years") or 1))
    return [Decimal(str(x)) for x in raw]


def phase_spend(total_cost: Any, fractions: Sequence[Any]) -> list[Decimal]:
    """Split ``total_cost`` by ``fractions``; the rounding remainder lands on the last year.

    The parts always add up to the cost to the cent, however the fractions round.
    """
    total = money(total_cost)
    if not fractions:
        return []
    parts = [money(total * Decimal(str(f))) for f in fractions[:-1]]
    parts.append(total - sum(parts, Decimal("0.00")))
    return parts


def item_spend_by_year(item: dict[str, Any]) -> dict[int, Decimal]:
    """``{calendar year: spend}`` for one item, ignoring its status."""
    start = int(item["start_year"])
    parts = phase_spend(item.get("total_cost"), phasing_fractions(item))
    return {start + i: amount for i, amount in enumerate(parts)}


def envelope_by_year(envelopes: Iterable[dict[str, Any]]) -> dict[int, Decimal]:
    """Sum the funding sources of each year."""
    out: dict[int, Decimal] = {}
    for env in envelopes:
        year = int(env["year"])
        out[year] = out.get(year, Decimal("0.00")) + money(env.get("amount"))
    return out


def plan_years(start_year: int, horizon_years: int) -> list[int]:
    return list(range(int(start_year), int(start_year) + int(horizon_years)))


def summarise(
    plan: dict[str, Any],
    envelopes: Iterable[dict[str, Any]],
    items: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Per-year demand / envelope / gap and per-item spend, plus totals.

    ``gap`` is envelope minus demand, so a negative gap is a shortfall. Demand counts
    items that are not deferred; spend outside the horizon is reported, not counted.
    """
    years = plan_years(plan["start_year"], plan["horizon_years"])
    env = envelope_by_year(envelopes)
    item_rows: list[dict[str, Any]] = []
    demand: dict[int, Decimal] = dict.fromkeys(years, Decimal("0.00"))
    beyond = Decimal("0.00")
    for item in items:
        spend = item_spend_by_year(item)
        if item.get("status") in ACTIVE_STATUSES:
            for year, amount in spend.items():
                if year in demand:
                    demand[year] += amount
                else:
                    beyond += amount
        item_rows.append(
            {
                "id": str(item.get("id")),
                "spend": {str(y): str(spend.get(y, Decimal("0.00"))) for y in years},
                "outside_horizon": str(sum((a for y, a in spend.items() if y not in demand), Decimal("0.00"))),
            }
        )
    rows: list[dict[str, Any]] = []
    cumulative = Decimal("0.00")
    for year in years:
        gap = env.get(year, Decimal("0.00")) - demand[year]
        cumulative += gap
        rows.append(
            {
                "year": year,
                "demand": str(demand[year]),
                "envelope": str(env.get(year, Decimal("0.00"))),
                "gap": str(gap),
                "cumulative_gap": str(cumulative),
            }
        )
    total_demand = sum(demand.values(), Decimal("0.00"))
    total_env = sum((env.get(y, Decimal("0.00")) for y in years), Decimal("0.00"))
    return {
        "years": years,
        "rows": rows,
        "items": item_rows,
        "totals": {
            "demand": str(total_demand),
            "envelope": str(total_env),
            "gap": str(total_env - total_demand),
            "beyond_horizon": str(beyond),
        },
    }


def _sort_key(item: dict[str, Any]) -> tuple[int, int, Decimal, str]:
    score = item.get("score")
    # Priority ascending, then score descending (unscored last), then cost ascending.
    return (
        int(item.get("priority") or 3),
        -(int(score) if score is not None else -1),
        money(item.get("total_cost")),
        str(item.get("id")),
    )


def autofund(envelopes: Iterable[dict[str, Any]], items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedy funding suggestion: priority asc, score desc, cost asc.

    An item is funded when its whole phased spend fits what is left of every year's
    envelope; otherwise it stays proposed with the first year it overflows. Deferred
    items are left alone. Returns one suggestion per non-deferred item, in processing
    order: ``{id, status, confidence, reason, changed}``.
    """
    remaining = dict(envelope_by_year(envelopes))
    out: list[dict[str, Any]] = []
    for item in sorted((i for i in items if i.get("status") in ACTIVE_STATUSES), key=_sort_key):
        spend = item_spend_by_year(item)
        zero = Decimal("0.00")
        overflow = next((y for y in sorted(spend) if spend[y] > remaining.get(y, zero)), None)
        if overflow is None:
            slack = [(remaining[y] - a) / remaining[y] for y, a in spend.items() if remaining.get(y)]
            for y, a in spend.items():
                remaining[y] = remaining.get(y, zero) - a
            has_cost = money(item.get("total_cost")) > 0
            if not has_cost:
                status, confidence, reason = "funded", 0.5, "no cost entered"
            else:
                tight = bool(slack) and min(slack) < Decimal("0.1")
                status, confidence, reason = "funded", 0.7 if tight else 0.9, "fits the envelope in every year"
        else:
            status, confidence, reason = "proposed", 0.8, f"exceeds envelope in {overflow}"
        out.append(
            {
                "id": str(item.get("id")),
                "status": status,
                "confidence": confidence,
                "reason": reason,
                "changed": status != item.get("status"),
            }
        )
    return out


def _item_key(item: dict[str, Any]) -> str:
    return f"p:{item['project_id']}" if item.get("project_id") else f"t:{item.get('title')}"


def compare(
    plan: dict[str, Any],
    envelopes: Sequence[dict[str, Any]],
    items_a: Sequence[dict[str, Any]],
    items_b: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Per-year demand and gap deltas (b minus a) and the items whose status or start year changed."""
    sa = summarise(plan, envelopes, items_a)
    sb = summarise(plan, envelopes, items_b)
    years = []
    for ra, rb in zip(sa["rows"], sb["rows"], strict=True):
        years.append(
            {
                "year": ra["year"],
                "demand_a": ra["demand"],
                "demand_b": rb["demand"],
                "delta_demand": str(Decimal(rb["demand"]) - Decimal(ra["demand"])),
                "gap_a": ra["gap"],
                "gap_b": rb["gap"],
                "delta_gap": str(Decimal(rb["gap"]) - Decimal(ra["gap"])),
            }
        )
    by_a = {_item_key(i): i for i in items_a}
    by_b = {_item_key(i): i for i in items_b}
    changed: list[dict[str, Any]] = []
    for key in sorted(by_a.keys() | by_b.keys()):
        a, b = by_a.get(key), by_b.get(key)
        if a is None or b is None:
            src = b or a
            changed.append({"title": src["title"], "change": "added" if a is None else "removed"})
        elif a["status"] != b["status"] or a["start_year"] != b["start_year"]:
            changed.append(
                {
                    "title": b["title"],
                    "change": "changed",
                    "status_a": a["status"],
                    "status_b": b["status"],
                    "start_year_a": a["start_year"],
                    "start_year_b": b["start_year"],
                }
            )
    return {
        "years": years,
        "changed_items": changed,
        "totals": {
            "delta_demand": str(Decimal(sb["totals"]["demand"]) - Decimal(sa["totals"]["demand"])),
            "delta_gap": str(Decimal(sb["totals"]["gap"]) - Decimal(sa["totals"]["gap"])),
        },
    }
