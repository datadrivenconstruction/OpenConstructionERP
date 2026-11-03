# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plug values for bid leveling: price the scope a bidder left out.

Two bids only compare on the same scope. A line a bidder did not price, or
priced as excluded, is a gap the main contractor will have to buy elsewhere, so
the leveling adds a plug for it. Where the plug comes from is always shown:

* ``manual``: typed by the estimator; it wins and survives a recompute.
* ``median``: the median of the other bidders' prices for the line, used first
  when at least two others priced it (the market for that line).
* ``estimate``: the bill rate of the line's BOQ position times the package
  quantity, when fewer than two others priced it.
* ``single_bid``: the one other bid that priced the line, when there is no estimate rate.
* ``none``: nothing to plug from; the gap stays at zero and is reported.

Only mandatory lines are gaps: an optional line nobody has to price is not
missing scope. Pure functions, no ORM, so the arithmetic is testable alone.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

_CENT = Decimal("0.01")

#: Inclusion statuses that leave the line's scope out of the bid.
GAP_STATUSES = frozenset({"excluded"})


@dataclass(frozen=True)
class Plug:
    """One plugged gap for one bidder."""

    bidder_id: Any
    line_item_id: Any
    amount: Decimal
    source: str
    reason: str
    note: str = ""


def _dec(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _priced(entry: tuple[Any, str] | None) -> Decimal | None:
    """The price of a line a bidder really priced, or ``None`` for a gap."""
    if entry is None:
        return None
    total, status = entry
    amount = _dec(total)
    if status in GAP_STATUSES or amount <= 0:
        return None
    return amount


def compute_plugs(
    package_lines: list[Any],
    priced: dict[Any, dict[Any, tuple[Any, str]]],
    *,
    estimate_rates: dict[Any, Decimal] | None = None,
    manual: dict[tuple[Any, Any], tuple[Decimal, str]] | None = None,
) -> dict[Any, list[Plug]]:
    """Plug every gap of every bidder.

    Args:
        package_lines: line items with ``id``, ``quantity`` and ``is_mandatory``.
        priced: per bidder, per line id, ``(total_price, inclusion_status)``.
        estimate_rates: unit rate from the estimate per line id.
        manual: estimator plugs per ``(bidder_id, line_id)`` as ``(amount, note)``.

    Returns:
        Per bidder id, the plugs for that bidder's gaps (empty list when none).
    """
    estimate_rates = estimate_rates or {}
    manual = manual or {}
    result: dict[Any, list[Plug]] = {bidder: [] for bidder in priced}
    for line in package_lines:
        if not getattr(line, "is_mandatory", True):
            continue
        line_id = line.id
        prices = {bidder: _priced(lines.get(line_id)) for bidder, lines in priced.items()}
        for bidder, own in prices.items():
            if own is not None:
                continue
            entry = priced[bidder].get(line_id)
            reason = "excluded" if entry is not None and entry[1] in GAP_STATUSES else "missing"
            if (bidder, line_id) in manual:
                amount, note = manual[(bidder, line_id)]
                result[bidder].append(Plug(bidder, line_id, _dec(amount).quantize(_CENT), "manual", reason, note))
                continue
            others = [p for b, p in prices.items() if b != bidder and p is not None]
            rate = estimate_rates.get(line_id)
            estimate = (_dec(rate) * _dec(line.quantity)).quantize(_CENT) if rate else None
            if len(others) >= 2:
                amount, source = Decimal(str(statistics.median(others))).quantize(_CENT), "median"
            elif estimate is not None and estimate > 0:
                amount, source = estimate, "estimate"
            elif others:
                amount, source = others[0].quantize(_CENT), "single_bid"
            else:
                amount, source = Decimal("0.00"), "none"
            result[bidder].append(Plug(bidder, line_id, amount, source, reason))
    return result


def plug_summary(plugs: list[Plug]) -> tuple[Decimal, int, int]:
    """(plug total, gap lines, gaps with nothing to plug from)."""
    total = sum((p.amount for p in plugs), Decimal("0")).quantize(_CENT)
    return total, len(plugs), sum(1 for p in plugs if p.source == "none")
