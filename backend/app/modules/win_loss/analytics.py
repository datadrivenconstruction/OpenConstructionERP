# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure maths of the ledger: money left on the table and the hit rate by group.

Standard library only. A row is any object with ``outcome``, ``our_price``,
``winning_price``, ``second_price``, ``client_name``, ``trade``, ``currency``.
No FX is applied: the summary covers one currency at a time.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

OUTCOMES = ("pending", "won", "lost", "withdrawn", "no_decision")
DECIDED = ("won", "lost")
LOST_REASONS = ("price", "scope", "schedule", "relationship", "capacity", "other")

#: Upper bounds (exclusive) of the size bands, in the entry currency.
SIZE_BANDS: tuple[tuple[str, Decimal | None], ...] = (
    ("small", Decimal("100000")),
    ("medium", Decimal("1000000")),
    ("large", Decimal("10000000")),
    ("major", None),
)

_CENT = Decimal("0.01")
_PCT = Decimal("0.1")
_ZERO = Decimal("0")


def _d(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _rate(won: int, decided: int) -> Decimal | None:
    return (Decimal(won) / decided * 100).quantize(_PCT, ROUND_HALF_UP) if decided else None


def size_band(price: Any) -> str:
    """Name the size band an own price falls in."""
    amount = _d(price) or _ZERO
    for name, bound in SIZE_BANDS:
        if bound is None or amount < bound:
            return name
    return SIZE_BANDS[-1][0]


def price_gap(row: Any) -> dict[str, Decimal | None]:
    """Money left on the table (won) or the gap to the winner (lost), amount and percent.

    Won: ``second_price - our_price``, what we could have asked and still won.
    Lost: ``our_price - winning_price``, what we would have had to cut.
    """
    ours = _d(row.our_price)
    out: dict[str, Decimal | None] = {
        "left_on_table": None,
        "left_on_table_pct": None,
        "gap_to_winner": None,
        "gap_to_winner_pct": None,
    }
    if not ours or ours <= 0:
        return out
    if row.outcome == "won":
        second = _d(row.second_price)
        if second is not None and second >= ours:
            out["left_on_table"] = (second - ours).quantize(_CENT)
            out["left_on_table_pct"] = ((second - ours) / ours * 100).quantize(_PCT, ROUND_HALF_UP)
    elif row.outcome == "lost":
        winner = _d(row.winning_price)
        if winner is not None and winner > 0:
            out["gap_to_winner"] = (ours - winner).quantize(_CENT)
            out["gap_to_winner_pct"] = ((ours - winner) / winner * 100).quantize(_PCT, ROUND_HALF_UP)
    return out


def _group(rows: list[Any], key: Callable[[Any], str]) -> list[dict[str, Any]]:
    buckets: dict[str, list[Any]] = {}
    for row in rows:
        buckets.setdefault(key(row), []).append(row)
    out: list[dict[str, Any]] = []
    for name, items in buckets.items():
        won = sum(1 for r in items if r.outcome == "won")
        lost = sum(1 for r in items if r.outcome == "lost")
        out.append(
            {
                "key": name,
                "submitted": len(items),
                "won": won,
                "lost": lost,
                "hit_rate_pct": _rate(won, won + lost),
                "won_value": sum((_d(r.our_price) or _ZERO for r in items if r.outcome == "won"), _ZERO),
            }
        )
    return sorted(out, key=lambda g: (-g["submitted"], g["key"]))


def summarize(rows: list[Any]) -> dict[str, Any]:
    """Headline numbers and the hit rate by client, trade and size for one currency's rows."""
    won = [r for r in rows if r.outcome == "won"]
    lost = [r for r in rows if r.outcome == "lost"]
    left = [g["left_on_table"] for g in map(price_gap, won) if g["left_on_table"] is not None]
    gaps = [g["gap_to_winner_pct"] for g in map(price_gap, lost) if g["gap_to_winner_pct"] is not None]
    competitors = [r.competitor_count for r in rows if r.competitor_count and r.outcome in DECIDED]
    return {
        "submitted": len(rows),
        "won": len(won),
        "lost": len(lost),
        "open": sum(1 for r in rows if r.outcome == "pending"),
        "hit_rate_pct": _rate(len(won), len(won) + len(lost)),
        "won_value": sum((_d(r.our_price) or _ZERO for r in won), _ZERO),
        "left_on_table": sum(left, _ZERO),
        "left_on_table_wins": len(left),
        "avg_gap_to_winner_pct": (sum(gaps, _ZERO) / len(gaps)).quantize(_PCT, ROUND_HALF_UP) if gaps else None,
        "avg_competitors": (Decimal(sum(competitors)) / len(competitors)).quantize(_PCT, ROUND_HALF_UP)
        if competitors
        else None,
        "by_client": _group(rows, lambda r: (r.client_name or "").strip()),
        "by_trade": _group(rows, lambda r: (r.trade or "").strip()),
        "by_size": _group(rows, lambda r: size_band(r.our_price)),
    }


def dominant_currency(rows: list[Any]) -> str:
    """The currency most rows use; ties go to the alphabetically first."""
    counts = Counter(r.currency or "" for r in rows)
    if not counts:
        return ""
    top = max(counts.values())
    return sorted(c for c, n in counts.items() if n == top)[0]
