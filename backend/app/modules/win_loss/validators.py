# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure checks on a bid outcome entry. The core rules ``bid_outcome.*`` wrap these.

Payload: ``{"title", "outcome", "currency", "our_price", "winning_price",
"second_price", "competitor_count", "lost_reason"}`` (strings or numbers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import sentence_amount


@dataclass(frozen=True)
class Finding:
    """One failed check; ``params`` fill the translated message."""

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _ref(payload: dict[str, Any]) -> str:
    return str(payload.get("title") or "bid")


def check_winner_recorded(payload: dict[str, Any]) -> list[Finding]:
    """A lost bid needs the winning price, or no gap can be measured."""
    if payload.get("outcome") != "lost" or (_dec(payload.get("winning_price")) or Decimal("0")) > 0:
        return []
    return [Finding(_ref(payload), {"bid": _ref(payload)})]


def check_won_matches_price(payload: dict[str, Any]) -> list[Finding]:
    """On a won bid the winning price is our own price."""
    winning, ours = _dec(payload.get("winning_price")), _dec(payload.get("our_price"))
    if payload.get("outcome") != "won" or winning is None or ours is None or winning == ours:
        return []
    cur = str(payload.get("currency") or "")
    return [
        Finding(
            _ref(payload),
            {"bid": _ref(payload), "ours": sentence_amount(ours, cur), "winning": sentence_amount(winning, cur)},
        )
    ]


def check_second_not_below_winner(payload: dict[str, Any]) -> list[Finding]:
    """The second price cannot be lower than the winning price."""
    winning, second = _dec(payload.get("winning_price")), _dec(payload.get("second_price"))
    if winning is None or second is None or second >= winning:
        return []
    cur = str(payload.get("currency") or "")
    return [
        Finding(
            _ref(payload),
            {"bid": _ref(payload), "second": sentence_amount(second, cur), "winning": sentence_amount(winning, cur)},
        )
    ]


def check_competitors_recorded(payload: dict[str, Any]) -> list[Finding]:
    """A decided bid should say how many other bidders it faced."""
    if payload.get("outcome") not in ("won", "lost") or (payload.get("competitor_count") or 0) >= 1:
        return []
    return [Finding(_ref(payload), {"bid": _ref(payload)})]


def check_lost_reason_recorded(payload: dict[str, Any]) -> list[Finding]:
    """A lost bid should carry a reason, so the next bid can learn from it."""
    if payload.get("outcome") != "lost" or payload.get("lost_reason"):
        return []
    return [Finding(_ref(payload), {"bid": _ref(payload)})]
