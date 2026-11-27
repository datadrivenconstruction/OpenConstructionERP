"""Replace one resource row of a position by a matched cost item.

The estimator searches the cost database for a better source of one resource
(``POST /costs/match/`` ranks candidates with a score), reads the candidate's
confidence, and confirms. This module only builds the replacement row: the
quantity and the type of the old row stay, the price, unit, name and code come
from the candidate, and the row records what it replaced and how confident the
match was, so the swap can be audited. The position rate is re-derived by the
normal update path; nothing here prices anything.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

REPLACED_KEY = "replaced_by_match"


class CandidateNotUsableError(ValueError):
    """The candidate cannot stand in for a resource row (inactive, unpriced, negative, or variant-bearing)."""


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def candidate_rate(item: Any) -> Decimal:
    """Unit rate of a cost item as Decimal; raises when the item cannot price a resource."""
    if not getattr(item, "is_active", True):
        raise CandidateNotUsableError("inactive")
    rate = _dec(getattr(item, "rate", None))
    if rate < 0:
        raise CandidateNotUsableError("negative_rate")
    return rate


def replacement_row(
    old: dict[str, Any],
    *,
    item: Any,
    currency: str,
    score: float | None,
    quantity: Decimal | None = None,
) -> dict[str, Any]:
    """The row that takes ``old``'s place, priced from ``item``."""
    rate = candidate_rate(item)
    qty = quantity if quantity is not None else _dec(old.get("quantity"))
    if qty < 0:
        raise CandidateNotUsableError("negative_quantity")
    row: dict[str, Any] = {
        "name": str(item.description or item.code)[:400],
        "code": str(item.code or ""),
        "type": str(old.get("type") or "other"),
        "unit": str(item.unit or old.get("unit") or ""),
        "quantity": float(qty),
        "unit_rate": float(rate),
        "total": float((qty * rate).quantize(Decimal("0.01"))),
        REPLACED_KEY: {
            "cost_item_id": str(item.id),
            "name": str(old.get("name") or ""),
            "code": str(old.get("code") or ""),
            "unit_rate": str(old.get("unit_rate") if old.get("unit_rate") is not None else ""),
            "score": None if score is None else round(float(score), 4),
        },
    }
    if currency:
        row["currency"] = currency
    return row
