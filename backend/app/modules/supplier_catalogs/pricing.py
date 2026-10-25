# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Net price resolution: list (gross) price minus the contractor's discount.

Pure functions, no session. Precedence, most specific first; inside one level
an agreement on the entry's price list beats one on the whole vendor:

    1. item, fixed net price
    2. item, percentage
    3. item category (the item's own category, then its parents, nearest first)
    4. overall (no category, no item)

Only active agreements valid on the pricing date count. Ties inside one level
go to the newest agreement (``created_at``), so the result never depends on
row order.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

NET_QUANT = Decimal("0.0001")
HUNDRED = Decimal("100")

SOURCE_NONE = "none"
SOURCE_ITEM_FIXED = "item_fixed"
SOURCE_ITEM = "item"
SOURCE_CATEGORY = "category"
SOURCE_OVERALL = "overall"
SOURCE_MANUAL = "manual"
DISCOUNT_SOURCES = (SOURCE_NONE, SOURCE_ITEM_FIXED, SOURCE_ITEM, SOURCE_CATEGORY, SOURCE_OVERALL, SOURCE_MANUAL)


class AgreementLike(Protocol):
    id: uuid.UUID
    vendor_id: uuid.UUID
    price_list_id: uuid.UUID | None
    category_id: uuid.UUID | None
    catalog_item_id: uuid.UUID | None
    discount_pct: Decimal | None
    fixed_net_price: Decimal | None
    valid_from: str | None
    valid_to: str | None
    active: bool


@dataclass(frozen=True)
class NetPrice:
    """The resolved price of one entry."""

    gross: Decimal
    net: Decimal
    discount_pct: Decimal | None
    source: str
    agreement_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gross_price": self.gross,
            "net_price": self.net,
            "discount_pct": self.discount_pct,
            "discount_source": self.source,
            "discount_agreement_id": self.agreement_id,
        }


def _day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def in_force(agreement: AgreementLike, on: date) -> bool:
    """Whether an agreement is active and its validity window covers ``on``."""
    if not agreement.active:
        return False
    start, end = _day(agreement.valid_from), _day(agreement.valid_to)
    return (start is None or start <= on) and (end is None or on <= end)


def apply_pct(gross: Decimal, pct: Decimal) -> Decimal:
    """``gross`` less ``pct`` percent, rounded half-up to four places."""
    return (gross * (HUNDRED - pct) / HUNDRED).quantize(NET_QUANT, rounding=ROUND_HALF_UP)


def _newest(agreements: list[Any]) -> Any:
    return max(
        agreements,
        key=lambda a: (getattr(a, "created_at", None) is not None, getattr(a, "created_at", None) or 0, str(a.id)),
    )


def resolve_net(
    *,
    gross: Decimal,
    vendor_id: uuid.UUID,
    price_list_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    category_chain: Sequence[uuid.UUID],
    agreements: Iterable[AgreementLike],
    on: date,
) -> NetPrice:
    """Resolve the net price of one catalogue entry.

    Args:
        gross: The entry's list price.
        vendor_id: The vendor of the entry's price list.
        price_list_id: The entry's price list.
        catalog_item_id: The entry's item.
        category_chain: The item's category, then its parent, grandparent and
            so on. Empty when the item has no category.
        agreements: Candidate agreements; ones of other vendors, other price
            lists or out of force are ignored here.
        on: The pricing date.
    """
    usable = [
        a
        for a in agreements
        if a.vendor_id == vendor_id
        and a.price_list_id in (None, price_list_id)
        and in_force(a, on)
        and (a.discount_pct is not None or a.fixed_net_price is not None)
    ]

    def pick(cands: list[Any]) -> Any | None:
        if not cands:
            return None
        on_list = [a for a in cands if a.price_list_id == price_list_id]
        return _newest(on_list or cands)

    item_level = [a for a in usable if a.catalog_item_id == catalog_item_id]
    fixed = pick([a for a in item_level if a.fixed_net_price is not None])
    if fixed is not None:
        net = Decimal(fixed.fixed_net_price).quantize(NET_QUANT, rounding=ROUND_HALF_UP)
        pct = ((gross - net) / gross * HUNDRED).quantize(NET_QUANT, rounding=ROUND_HALF_UP) if gross else None
        return NetPrice(gross, net, pct, SOURCE_ITEM_FIXED, fixed.id)
    chosen = pick([a for a in item_level if a.discount_pct is not None])
    source = SOURCE_ITEM
    if chosen is None:
        for cat in category_chain:
            chosen = pick(
                [a for a in usable if a.catalog_item_id is None and a.category_id == cat and a.discount_pct is not None]
            )
            if chosen is not None:
                source = SOURCE_CATEGORY
                break
    if chosen is None:
        chosen = pick(
            [a for a in usable if a.catalog_item_id is None and a.category_id is None and a.discount_pct is not None]
        )
        source = SOURCE_OVERALL
    if chosen is None:
        return NetPrice(gross, gross, None, SOURCE_NONE, None)
    pct = Decimal(chosen.discount_pct)
    return NetPrice(gross, apply_pct(gross, pct), pct, source, chosen.id)


def category_chain(category_id: uuid.UUID | None, parents: dict[uuid.UUID, uuid.UUID | None]) -> list[uuid.UUID]:
    """The category and its ancestors, nearest first, cycle-safe."""
    chain: list[uuid.UUID] = []
    current = category_id
    while current is not None and current not in chain and len(chain) < 32:
        chain.append(current)
        current = parents.get(current)
    return chain
