"""Turn a priced BOQ position into a cost item, or refresh a cost item from one.

An estimator builds a priced line in a bill (description, unit, a resource
composition) and wants it in their own cost database for the next job. This
module holds the pure mapping from a position to the cost item payload; the
router does the access checks and the persistence through ``CostItemService``.

Money stays Decimal end to end: the unit rate is the position's stored unit
rate, each component cost is ``quantity * unit_rate`` quantised to cents, and
nothing is converted between currencies.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field

# Region of the user's own database when neither the request nor the position names one.
DEFAULT_REGION = "CUSTOM"
SAVED_FROM_KEY = "saved_from_boq_position"
# Unit the BOQ stores on a section row; a section is a heading, not a priced line.
SECTION_UNIT = "section"

_CENT = Decimal("0.01")


class CostItemFromPositionRequest(BaseModel):
    """Optional overrides when saving a position as a cost item."""

    code: str | None = Field(default=None, min_length=1, max_length=100)
    region: str | None = Field(default=None, min_length=1, max_length=50)
    catalog_id: uuid.UUID | None = None


class CostItemRefreshRequest(BaseModel):
    """The position a cost item is refreshed from."""

    position_id: uuid.UUID


class PositionNotSavableError(ValueError):
    """The position cannot become a cost item (a section, or it carries no unit)."""


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def default_code(position_id: uuid.UUID) -> str:
    """Stable code for a position, so saving it twice meets the duplicate check."""
    return f"MY-{position_id.hex[:8].upper()}"


def components_from_resources(resources: Any) -> list[dict[str, Any]]:
    """Per-unit components from the resource rows of a position.

    Rows without a name are dropped. Quantities and rates are kept as the row
    states them; ``cost`` is derived, rounded half-up to cents.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(resources, list):
        return out
    for row in resources:
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            continue
        qty = _dec(row.get("quantity"))
        rate = _dec(row.get("unit_rate"))
        comp: dict[str, Any] = {
            "name": str(row["name"]).strip(),
            "code": str(row.get("code") or ""),
            "type": str(row.get("type") or "other"),
            "unit": str(row.get("unit") or ""),
            "quantity": str(qty),
            "unit_rate": str(rate),
            "cost": str((qty * rate).quantize(_CENT, rounding=ROUND_HALF_UP)),
        }
        currency = str(row.get("currency") or "").strip()
        if currency:
            comp["currency"] = currency
        out.append(comp)
    return out


def cost_item_fields_from_position(
    *,
    position_id: uuid.UUID,
    description: str | None,
    unit: str | None,
    unit_rate: Any,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fields a cost item takes from a position: description, unit, rate, components, currency.

    Raises:
        PositionNotSavableError: for a section (no unit) or a position without a description.
    """
    unit_s = (unit or "").strip()
    desc_s = (description or "").strip()
    if not unit_s or unit_s.lower() == SECTION_UNIT or not desc_s:
        raise PositionNotSavableError("position has no unit or description")
    meta = metadata or {}
    rate = _dec(unit_rate)
    if rate < 0:
        raise PositionNotSavableError("position has a negative unit rate")
    return {
        "description": desc_s,
        "unit": unit_s[:20],
        "rate": rate,
        "currency": str(meta.get("currency") or ""),
        "components": components_from_resources(meta.get("resources")),
        "metadata": {SAVED_FROM_KEY: str(position_id)},
    }


def resolve_region(requested: str | None, position_metadata: dict[str, Any] | None) -> str:
    """Request first, then the region the position was priced from, then the user's own database."""
    if requested and requested.strip():
        return requested.strip()
    stamped = (position_metadata or {}).get("cost_item_region")
    if isinstance(stamped, str) and stamped.strip():
        return stamped.strip()
    return DEFAULT_REGION
