# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How much of a change order raises each order or subcontract it touches.

A change order linked to one purchase order raises that order by its whole
amount. One that touches several commitments says how its amount splits:
``commitment_allocations`` is a list of ``{"kind", "id", "amount"}``, where
``kind`` is ``purchase_order`` or ``subcontract``. The allocations must add up
to the change order amount. Until a multi-commitment change order is allocated
it raises nothing, and the invoice and change order checks say so.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

KIND_PURCHASE_ORDER = "purchase_order"
KIND_SUBCONTRACT = "subcontract"
KINDS = frozenset({KIND_PURCHASE_ORDER, KIND_SUBCONTRACT})


def _dec(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _uuid(raw: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw)) if raw else None
    except (ValueError, TypeError):
        return None


def allocations_of(raw: object) -> list[dict[str, Any]]:
    """The well-formed allocations of a stored value: kind, id (UUID) and amount (Decimal)."""
    out: list[dict[str, Any]] = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        kind, target, amount = row.get("kind"), _uuid(row.get("id")), _dec(row.get("amount"))
        if kind in KINDS and target is not None and amount is not None:
            out.append({"kind": kind, "id": target, "amount": amount})
    return out


def allocated_to(raw: object, kind: str, commitment_id: uuid.UUID) -> Decimal | None:
    """What the allocations give one commitment, or ``None`` when they do not name it."""
    found = [a["amount"] for a in allocations_of(raw) if a["kind"] == kind and a["id"] == commitment_id]
    return sum(found, Decimal("0")) if found else None


def commitments_touched(linked_po_ids: object, raw_allocations: object) -> int:
    """How many distinct commitments a change order names, by link or by allocation."""
    named = {(KIND_PURCHASE_ORDER, x) for x in (_uuid(v) for v in (linked_po_ids or [])) if x is not None}
    named |= {(a["kind"], a["id"]) for a in allocations_of(raw_allocations)}
    return len(named)


def to_json(rows: list[Any] | None) -> list[dict[str, str]] | None:
    """The JSON-safe stored form of allocations given as dicts or models."""
    if rows is None:
        return None
    out: list[dict[str, str]] = []
    for row in rows:
        data = row if isinstance(row, dict) else row.model_dump()
        out.append({"kind": str(data["kind"]), "id": str(data["id"]), "amount": str(data["amount"])})
    return out
