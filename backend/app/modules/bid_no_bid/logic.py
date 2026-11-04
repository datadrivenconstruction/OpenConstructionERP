# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scorecard arithmetic: pure functions, no database."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Every rating reads "5 = good for us": strong client, free capacity, low risk, healthy margin, weak competition.
CRITERIA: tuple[str, ...] = ("client", "capacity", "risk", "margin", "competition")
DEFAULT_WEIGHTS: dict[str, int] = {"client": 20, "capacity": 20, "risk": 20, "margin": 25, "competition": 15}
DEFAULT_THRESHOLD = 60
MIN_RATING, MAX_RATING = 1, 5


def to_int(value: Any) -> int | None:
    """An integer from a JSON value, or None when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def clean_weights(raw: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in CRITERIA:
        n = to_int((raw or {}).get(key))
        out[key] = n if n is not None else DEFAULT_WEIGHTS[key]
    return out


def clean_scores(raw: dict[str, Any] | None) -> dict[str, int | None]:
    return {key: to_int((raw or {}).get(key)) for key in CRITERIA}


def weighted_score(weights: dict[str, int], scores: dict[str, int | None]) -> Decimal | None:
    """0-100 score, or None until every criterion is rated and the weights are usable."""
    if any(s is None for s in scores.values()):
        return None
    total = sum(max(weights.get(k, 0), 0) for k in CRITERIA)
    if total <= 0:
        return None
    got = sum(max(weights.get(k, 0), 0) * int(scores[k] or 0) for k in CRITERIA)
    return (Decimal(got) * 100 / Decimal(total * MAX_RATING)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def recommendation(score: Decimal | None, threshold: int) -> str:
    """'bid' at or above the threshold, 'no_bid' below it, '' while unscored."""
    if score is None:
        return ""
    return "bid" if score >= Decimal(threshold) else "no_bid"


def win_loss_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the ledger: decisions, outcomes and the win rate of the bids that were closed."""
    bids = [r for r in rows if r["decision"] == "bid"]
    won = sum(1 for r in bids if r["outcome"] == "won")
    lost = sum(1 for r in bids if r["outcome"] == "lost")
    closed = won + lost
    return {
        "total": len(rows),
        "bid": len(bids),
        "no_bid": sum(1 for r in rows if r["decision"] == "no_bid"),
        "undecided": sum(1 for r in rows if not r["decision"]),
        "won": won,
        "lost": lost,
        "win_rate_pct": str((Decimal(won) * 100 / Decimal(closed)).quantize(Decimal("0.1"))) if closed else None,
    }
