# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The resources of one BOQ, offered as scope lines for an RFQ.

A buyer asks suppliers to price what the estimate consumes: the concrete, the
rebar, the crane days. Those live as resource rows on BOQ positions
(``Position.metadata_["resources"]``), stored as per-unit norms, so the amount
a position consumes is the norm times the position quantity. The same resource
usually appears on many positions; a supplier prices it once, so rows that
share category, code or name, and unit are summed into one option.

Each option carries a short ``key`` derived from what it is, not where it sits,
so a create request can name its picks and the server recomputes the options
from the BOQ it trusts instead of taking quantities from the client.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.price_breakdown import coerce_kind

#: Unit used for a resource row that names none; a supplier then prices a lump.
FALLBACK_UNIT = "lot"

#: How many contributing position ids an RFQ line keeps in its metadata.
MAX_TRACKED_POSITIONS = 50

_QUANTITY_QUANTUM = Decimal("0.0001")


@dataclass
class BoqResourceOption:
    """One resource of a BOQ, summed over every position that uses it."""

    key: str
    name: str
    code: str | None
    category: str
    unit: str
    quantity: Decimal = Decimal("0")
    position_ids: list[str] = field(default_factory=list)


def _decimal(value: Any) -> Decimal | None:
    """A finite Decimal out of a JSON value, or None."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        out = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def resource_key(category: str, code: str | None, name: str, unit: str) -> str:
    """A short stable identifier for one aggregated resource."""
    identity = "\x1f".join((category, (code or "").strip().lower(), name.strip().lower(), unit.strip().lower()))
    return hashlib.sha1(identity.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]


def aggregate_resources(positions: Iterable[tuple[str, Any, Mapping[str, Any] | None]]) -> list[BoqResourceOption]:
    """Sum the resource rows of BOQ positions into one option per resource.

    Args:
        positions: ``(position_id, position_quantity, position_metadata)`` per
            position. Rows without a name or with an unreadable quantity are
            skipped; a position with an unreadable quantity contributes nothing.

    Returns:
        The options sorted by category, then name.
    """
    options: dict[str, BoqResourceOption] = {}
    for position_id, position_quantity, metadata in positions:
        pos_qty = _decimal(position_quantity)
        if pos_qty is None or not isinstance(metadata, Mapping):
            continue
        rows = metadata.get("resources")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            norm = _decimal(row.get("quantity"))
            if norm is None:
                continue
            code = str(row.get("code") or "").strip() or None
            unit = str(row.get("unit") or "").strip() or FALLBACK_UNIT
            category = coerce_kind(row.get("type") or row.get("resource_type") or row.get("kind")).value
            key = resource_key(category, code, name, unit)
            option = options.get(key)
            if option is None:
                option = BoqResourceOption(key=key, name=name, code=code, category=category, unit=unit)
                options[key] = option
            option.quantity += norm * pos_qty
            if position_id not in option.position_ids:
                option.position_ids.append(position_id)
    for option in options.values():
        option.quantity = option.quantity.quantize(_QUANTITY_QUANTUM)
    return sorted(options.values(), key=lambda o: (o.category, o.name.lower(), o.unit))


async def load_boq_resources(session: AsyncSession, boq_id: uuid.UUID) -> list[BoqResourceOption]:
    """The aggregated resources of one BOQ."""
    from app.modules.boq.models import Position

    result = await session.execute(
        select(Position.id, Position.quantity, Position.metadata_).where(Position.boq_id == boq_id)
    )
    return aggregate_resources((str(pid), qty, meta) for pid, qty, meta in result.all())


async def boq_project_id(session: AsyncSession, boq_id: uuid.UUID) -> uuid.UUID | None:
    """The project a BOQ belongs to, or None when the BOQ does not exist."""
    from app.modules.boq.models import BOQ

    return (await session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).scalar_one_or_none()
