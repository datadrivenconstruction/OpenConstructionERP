# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day arithmetic: normalised quotes, row values, markups, totals and suggestions.

Pure functions on plain data, no I/O, ``Decimal`` throughout. The service maps
ORM rows to :class:`QuoteData` / :class:`RowData` and returns what these give.

Normalisation: every quote is converted to the board currency at the rate stored
on it, then each exclusion the estimator plugged adds its plug amount. That is
the "adjusted" figure; "as quoted" is the converted amount alone. Exclusions
still ``open`` are unresolved: the quote does not yet cover the scope.

Bid total: direct cost is the sum of row values (the chosen quote's adjusted
figure, otherwise the estimate's plug). Overhead and risk are percentages of
direct cost, profit a percentage of direct cost plus overhead plus risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
EXCLUSION_STATES = frozenset({"open", "plugged", "included"})


def to_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    """Read a number or numeric string; anything unreadable gives ``default``."""
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    try:
        out = Decimal(str(value).strip().replace(" ", ""))
    except (InvalidOperation, ValueError):
        return default
    return out if out.is_finite() else default


def money(value: Decimal) -> Decimal:
    """Round to cents, half up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value: Decimal) -> str:
    """Serialise money as a plain decimal string with two places."""
    return f"{money(value):f}"


@dataclass
class QuoteData:
    id: str
    vendor: str
    amount: Decimal
    fx_rate: Decimal = Decimal("1")
    exclusions: list[dict[str, Any]] = field(default_factory=list)
    received_at: datetime | None = None


@dataclass
class RowData:
    id: str
    name: str
    plug: Decimal
    quotes: list[QuoteData] = field(default_factory=list)
    chosen_id: str | None = None


@dataclass
class Markups:
    overhead_pct: Decimal = ZERO
    risk_pct: Decimal = ZERO
    profit_pct: Decimal = ZERO


def clean_exclusions(raw: Any) -> list[dict[str, Any]]:
    """Normalise an exclusion list: id, text, status, plug amount as a string."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "open")
        if status not in EXCLUSION_STATES:
            status = "open"
        plug = to_decimal(item.get("plug_amount"))
        out.append(
            {
                "id": str(item.get("id") or f"x{i + 1}"),
                "text": str(item.get("text") or "")[:500],
                "status": status,
                "plug_amount": fmt(plug) if status == "plugged" else "0.00",
            }
        )
    return out


def as_quoted(q: QuoteData) -> Decimal:
    """The quote in board currency, before scope plugs."""
    return money(q.amount * q.fx_rate)


def plugs(q: QuoteData) -> Decimal:
    """Sum of the plugs the estimator added for scope the quote leaves out."""
    return sum(
        (to_decimal(x.get("plug_amount")) for x in q.exclusions if x.get("status") == "plugged"),
        ZERO,
    )


def adjusted(q: QuoteData) -> Decimal:
    """The like-for-like figure: as quoted plus plugs for missing scope."""
    return money(as_quoted(q) + plugs(q))


def open_exclusions(q: QuoteData) -> int:
    return sum(1 for x in q.exclusions if x.get("status", "open") == "open")


def chosen(row: RowData) -> QuoteData | None:
    return next((q for q in row.quotes if q.id == row.chosen_id), None)


def row_value(row: RowData) -> Decimal:
    """What the row puts into direct cost: the chosen quote adjusted, else the plug."""
    q = chosen(row)
    return adjusted(q) if q is not None else money(row.plug)


def suggest(row: RowData) -> dict[str, Any] | None:
    """The best-value quote of a row with a confidence and a coded reason.

    Lowest adjusted figure wins. Confidence starts at 0.6 and moves with how much
    competition there is, whether the winner still has open exclusions and how
    clear the gap to the runner-up is. ``reasons`` are codes the UI translates.
    """
    if not row.quotes:
        return None
    ranked = sorted(row.quotes, key=lambda q: (adjusted(q), q.vendor))
    best = ranked[0]
    conf = Decimal("0.6")
    reasons = ["lowest_adjusted"]
    gap_pct = ZERO
    if len(ranked) == 1:
        conf -= Decimal("0.3")
        reasons.append("single_quote")
    else:
        second = adjusted(ranked[1])
        if second > 0:
            gap_pct = (second - adjusted(best)) / second * HUNDRED
        if len(ranked) >= 3:
            conf += Decimal("0.15")
            reasons.append("competitive")
        if gap_pct >= 3:
            conf += Decimal("0.1")
            reasons.append("clear_gap")
        elif gap_pct < 1:
            conf -= Decimal("0.1")
            reasons.append("close_call")
    n_open = open_exclusions(best)
    if n_open:
        conf -= Decimal("0.2")
        reasons.append("open_exclusions")
    elif plugs(best) > 0:
        reasons.append("plugged_scope")
    conf = min(max(conf, Decimal("0.05")), Decimal("0.95"))
    return {
        "quote_id": best.id,
        "vendor": best.vendor,
        "adjusted": fmt(adjusted(best)),
        "confidence": float(conf.quantize(Decimal("0.01"))),
        "reasons": reasons,
        "gap_pct": float(gap_pct.quantize(Decimal("0.1"))),
        "open_exclusions": n_open,
        "is_chosen": best.id == row.chosen_id,
    }


def totals(rows: list[RowData], m: Markups, *, last_snapshot_total: Decimal | None = None) -> dict[str, str | None]:
    """Direct cost, each markup, bid total, estimate baseline and delta to the last snapshot."""
    direct = sum((row_value(r) for r in rows), ZERO)
    estimate = sum((money(r.plug) for r in rows), ZERO)
    overhead = money(direct * m.overhead_pct / HUNDRED)
    risk = money(direct * m.risk_pct / HUNDRED)
    profit = money((direct + overhead + risk) * m.profit_pct / HUNDRED)
    markup = overhead + risk + profit
    total = direct + markup
    est_total = estimate + money(estimate * m.overhead_pct / HUNDRED) + money(estimate * m.risk_pct / HUNDRED)
    est_total += money(est_total * m.profit_pct / HUNDRED)
    return {
        "direct": fmt(direct),
        "overhead": fmt(overhead),
        "risk": fmt(risk),
        "profit": fmt(profit),
        "markup": fmt(markup),
        "bid_total": fmt(total),
        "estimate_direct": fmt(estimate),
        "estimate_total": fmt(est_total),
        "vs_estimate": fmt(direct - estimate),
        "last_snapshot_total": fmt(last_snapshot_total) if last_snapshot_total is not None else None,
        "delta_vs_snapshot": fmt(total - last_snapshot_total) if last_snapshot_total is not None else None,
    }


def bid_total(rows: list[RowData], m: Markups) -> Decimal:
    return to_decimal(totals(rows, m)["bid_total"])


def deviation_pct(direct: Decimal, estimate: Decimal) -> Decimal | None:
    """How far direct cost is from the estimate, in percent; ``None`` without an estimate."""
    if estimate == 0:
        return None
    return (direct - estimate) / estimate * HUNDRED
