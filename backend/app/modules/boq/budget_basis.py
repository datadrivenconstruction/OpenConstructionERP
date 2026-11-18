# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost budget of a bill position: target cost when it has one.

A contractor's bill carries three rates per position: the net cost the
estimate was built from, the target cost the site team is held to, and the
sale rate the client pays (``unit_rate``). Once the job is won, the budget the
commercial team controls against is the target cost, not the price.

So every reader that needs "what may this position cost" (the commitment grid,
the CVR rollup) asks this module, and they all give the same answer:

* ``target_rate`` set: budget = quantity x target_rate, basis ``target``;
* otherwise: budget = quantity x unit_rate, basis ``unit_rate``, which is the
  figure those readers used before target cost existed.

The basis travels with the number, so a screen can say which positions are
still budgeted at the sale rate and the ``cvr.target_rate_basis`` rule can warn
about them. Pure: plain attribute-bearing objects in, Decimals out.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

BASIS_TARGET = "target"
BASIS_UNIT_RATE = "unit_rate"

#: Units that mark a section header row, as in ``boq.service.SECTION_UNITS``.
_SECTION_UNITS = frozenset({"", "section"})


def _dec(raw: object) -> Decimal | None:
    """Parse a stored money/quantity string; ``None`` when blank or unreadable."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


@dataclass(frozen=True)
class PositionBudget:
    """Budget quantity, rate and value of one position, and where the rate came from."""

    quantity: Decimal
    rate: Decimal
    amount: Decimal
    basis: str


def is_priced_line(position: object) -> bool:
    """True for a measured, priced line; False for a section header or an empty row."""
    unit = str(getattr(position, "unit", "") or "").strip().lower()
    qty = _dec(getattr(position, "quantity", None)) or Decimal("0")
    rate = _dec(getattr(position, "unit_rate", None)) or Decimal("0")
    target = _dec(getattr(position, "target_rate", None))
    if unit in _SECTION_UNITS and qty == 0 and rate == 0:
        return False
    return qty != 0 or rate != 0 or target is not None


def position_budget(position: object) -> PositionBudget:
    """Budget of one position: quantity x target rate, else quantity x unit rate."""
    qty = _dec(getattr(position, "quantity", None)) or Decimal("0")
    target = _dec(getattr(position, "target_rate", None))
    if target is not None:
        return PositionBudget(quantity=qty, rate=target, amount=qty * target, basis=BASIS_TARGET)
    rate = _dec(getattr(position, "unit_rate", None)) or Decimal("0")
    return PositionBudget(quantity=qty, rate=rate, amount=qty * rate, basis=BASIS_UNIT_RATE)


def sale_value(position: object) -> Decimal:
    """What the client pays for the position: quantity x sale rate, else its total."""
    qty = _dec(getattr(position, "quantity", None)) or Decimal("0")
    sale = _dec(getattr(position, "sale_rate", None))
    if sale is not None:
        return qty * sale
    total = _dec(getattr(position, "total", None))
    if total is not None:
        return total
    return qty * (_dec(getattr(position, "unit_rate", None)) or Decimal("0"))
