# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How the resource quantities of one position were entered.

Stored resource rows always follow the per-unit norm convention: ``quantity``
is the amount of the resource per ONE unit of the position, so
``sum(quantity * unit_rate)`` is the position's unit rate and every reader
(rollups, exports, procurement, schedule, resource summary) can rely on that.

Estimators work two ways, though. Catalogue build-ups are per-unit norms
("0.12 t of rebar per m3"), while a hand-priced item is often written as the
resources the whole item consumes ("50 poles at 500 for 50 poles"). Read as a
norm, the second form multiplies the position by its own quantity a second
time. So a position can declare ``metadata.resource_quantity_basis``:

* ``per_unit`` (default, absent key): rows are entered and shown as norms.
* ``per_position``: rows are entered and shown as quantities for the whole
  position. Each row keeps what was entered in ``quantity_for_position`` and
  its norm is derived from it, ``quantity = quantity_for_position / position
  quantity``. The position's unit rate is then the resources total divided by
  the position quantity, and a change of the position quantity keeps the
  entered totals and re-derives the norms instead of scaling the resources.

Everything here is pure and database-free.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

#: Position metadata key naming how the resource quantities were entered.
BASIS_KEY = "resource_quantity_basis"

#: Resource quantities are per one unit of the position (the stored norm).
PER_UNIT = "per_unit"

#: Resource quantities are totals for the whole position.
PER_POSITION = "per_position"

#: Row key holding the quantity entered for the whole position.
ROW_POSITION_QUANTITY_KEY = "quantity_for_position"

#: Row ``total`` (the per-unit subtotal) is stored at the line-storage precision.
_ROW_TOTAL_QUANTUM = Decimal("0.0001")


def _dec(value: Any) -> Decimal | None:
    """A finite Decimal out of a JSON value, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _json_number(value: Decimal) -> int | float:
    """A JSON number for a row field; the frontend does arithmetic on these."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def resource_basis(metadata: Any) -> str:
    """The basis the position declares; anything unknown reads as per-unit."""
    if isinstance(metadata, dict) and metadata.get(BASIS_KEY) == PER_POSITION:
        return PER_POSITION
    return PER_UNIT


def apply_resource_basis(metadata: dict[str, Any], position_quantity: Any) -> bool:
    """Bring the rows of ``metadata.resources`` in line with the declared basis.

    Per-position: every row gets ``quantity_for_position`` (filled from its norm
    when the row has none yet, e.g. a row just added from the catalogue) and
    its norm ``quantity`` is re-derived from it. Per-unit: the per-position key
    is dropped and the norms stay as they are. Rows are mutated in place, so
    the caller passes a metadata dict it owns.

    A position quantity of zero or less cannot be divided by, so the rows are
    left untouched in that case.

    Returns:
        True when any row changed.
    """
    rows = metadata.get("resources")
    if not isinstance(rows, list):
        return False
    changed = False
    if resource_basis(metadata) != PER_POSITION:
        for row in rows:
            if isinstance(row, dict) and ROW_POSITION_QUANTITY_KEY in row:
                row.pop(ROW_POSITION_QUANTITY_KEY)
                changed = True
        return changed

    qty = _dec(position_quantity)
    if qty is None or qty <= 0:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        entered = _dec(row.get(ROW_POSITION_QUANTITY_KEY))
        if entered is None:
            norm = _dec(row.get("quantity")) or Decimal("0")
            entered = norm * qty
            row[ROW_POSITION_QUANTITY_KEY] = _json_number(entered)
            changed = True
        norm = entered / qty
        stored_norm = _json_number(norm)
        if row.get("quantity") != stored_norm:
            row["quantity"] = stored_norm
            changed = True
        rate = _dec(row.get("unit_rate")) or Decimal("0")
        row_total = _json_number((norm * rate).quantize(_ROW_TOTAL_QUANTUM))
        if row.get("total") != row_total:
            row["total"] = row_total
            changed = True
    return changed


def rows_at_position_quantities(resources: Any) -> list[dict[str, Any]]:
    """Copies of the rows with ``quantity`` set to the whole-position quantity.

    Summing ``quantity * unit_rate`` over the result gives the resources total
    of the whole position straight from what was entered, without going
    through a norm that may not terminate (10 units over a quantity of 3).
    Call it after :func:`apply_resource_basis`, which fills the key on every row.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(resources, list):
        return out
    for row in resources:
        if not isinstance(row, dict):
            continue
        copy = dict(row)
        entered = _dec(row.get(ROW_POSITION_QUANTITY_KEY))
        if entered is not None:
            copy["quantity"] = str(entered)
        out.append(copy)
    return out
