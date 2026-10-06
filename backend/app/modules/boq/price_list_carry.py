# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill line created from a regional price list keeps saying which list it is from.

The price-list import leaves the list's region, edition, licence and the
item's shares on the cost item, under ``metadata["prezzario"]``. The Italian
rules read that block on the bill line: it is what tells an official
unprefixed code ("1.1.20.1", Umbria) from one typed by hand, what states the
labour share the tender has to show, and what marks a rate as a list price
with general expenses and profit already in it. A line that does not carry it
is judged as hand-written, so every route that makes a line out of a cost item
copies it here, and every route that copies a line copies it along.

Routes and what they do (the list the review asked for; keep it current):

* Add from the cost database (the BOQ editor's modal) - the item's id rides in
  ``metadata.cost_item_id``; :meth:`BOQService.add_position` carries.
* Add to BOQ from the costs page, takeoff, AI proposals, chat - top-level
  ``cost_item_id`` or none; :meth:`BOQService.add_position` carries.
* Bulk add (imports with a cost item per row) - the bulk create carries.
* Linking or re-linking a line to an item, including the grid autocomplete -
  :meth:`BOQService.update_position` carries, and replaces or drops the block
  when the link moves to another item.
* Apply a CAD-BIM match, apply an AI estimate, apply a cost match - each
  resolves its cost item and carries.
* Re-derive resources from the linked item (resource review) - carries.
* Duplicate a line, duplicate or revise a bill, restore a snapshot - copy the
  metadata whole, block included.
* Seed a variation from bill lines - copies the provenance keys
  (:func:`provenance_of`).

Deliberately not carried: an assembly applied to the bill is the estimator's
own analysis of several items, not a list price, and saying it is one would
make the general expenses check count its markups twice; the CWICR resource
enrichment picks its item by a fuzzy text match, and stamping a list's
provenance from a guess would state as fact what nobody confirmed.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

PRICE_LIST_KEY = "prezzario"

# What a bill line needs from the item's block: which list and edition, under
# which licence, the shares the rules and the tender read, and whether the
# rate includes general expenses and profit. The chapter path, the analysis
# record and the import flags stay on the cost item; a bill of a thousand
# lines does not need a thousand copies of them.
CARRIED_KEYS: tuple[str, ...] = (
    "region",
    "region_code",
    "edition",
    "area",
    "format",
    "licence",
    "licence_stated_in",
    "attribution",
    "source_unit",
    "safety",
    "labour_share_pct",
    "labour_amount",
    "safety_share_pct",
    "safety_amount",
    "overhead_pct",
    "profit_pct",
    "material_share_pct",
    "equipment_share_pct",
    "rate_includes_overheads",
)

# The keys a copied line keeps so the rules still know where it came from.
PROVENANCE_KEYS: tuple[str, ...] = (PRICE_LIST_KEY, "cost_shares", "xpwe_ep_id", "safety_item", "cost_item_id")


def price_list_block(cost_item: Any) -> dict[str, Any] | None:
    """The part of the item's price-list block a bill line carries, or ``None``."""
    metadata = getattr(cost_item, "metadata_", None)
    block = metadata.get(PRICE_LIST_KEY) if isinstance(metadata, dict) else None
    if not isinstance(block, dict) or not block:
        return None
    carried = {key: block[key] for key in CARRIED_KEYS if key in block}
    return carried or None


def carry_block(metadata: dict[str, Any], cost_item: Any, *, replace: bool = False) -> None:
    """Write the item's block onto a line's ``metadata``.

    Args:
        metadata: The line's metadata, changed in place.
        cost_item: The cost item the line is linked to.
        replace: The line is being linked to a different item: a block the
            new item does not have is removed, so the line never keeps the
            region and shares of the item it was linked to before.
    """
    block = price_list_block(cost_item)
    if block is not None:
        metadata[PRICE_LIST_KEY] = block
    elif replace:
        metadata.pop(PRICE_LIST_KEY, None)


def linked_cost_item_id(metadata: dict[str, Any] | None) -> uuid.UUID | None:
    """The cost item ``metadata.cost_item_id`` names, or ``None`` when it names none readable."""
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("cost_item_id")
    if raw in (None, ""):
        return None
    try:
        return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


async def load_cost_item(session: AsyncSession, item_id: uuid.UUID | str | None) -> Any | None:
    """The active cost item ``item_id`` names, or ``None``.

    The routes that carry by the id in the metadata never refused a line for
    a stale link, so a missing or retired item is not an error here either:
    the line is simply added without a block.
    """
    if item_id in (None, ""):
        return None
    try:
        key = item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
    except (TypeError, ValueError):
        return None
    from app.modules.costs.repository import CostItemRepository

    item = await CostItemRepository(session).get_by_id(key)
    if item is None or not getattr(item, "is_active", False):
        return None
    return item


async def carry_from_link(
    session: AsyncSession,
    metadata: dict[str, Any],
    *,
    cost_item: Any | None = None,
    replace: bool = False,
) -> None:
    """Carry the block of the item the line is linked to, loading it by ``metadata.cost_item_id`` if needed.

    Args:
        session: The request's session.
        metadata: The line's metadata, changed in place.
        cost_item: The item when the caller already loaded it.
        replace: See :func:`carry_block`.
    """
    item = cost_item if cost_item is not None else await load_cost_item(session, linked_cost_item_id(metadata))
    # An unresolved replacement cannot keep the previous item's provenance.
    # Ordinary creation still keeps an explicitly supplied block as before.
    if item is not None or replace:
        carry_block(metadata, item, replace=replace)


def provenance_of(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """The keys of a line's metadata that say where its rate came from, for a line copied from it."""
    if not isinstance(metadata, dict):
        return {}
    out: dict[str, Any] = {}
    for key in PROVENANCE_KEYS:
        if key in metadata:
            value = metadata[key]
            out[key] = dict(value) if isinstance(value, dict) else value
    return out


__all__ = [
    "CARRIED_KEYS",
    "PRICE_LIST_KEY",
    "PROVENANCE_KEYS",
    "carry_block",
    "carry_from_link",
    "linked_cost_item_id",
    "load_cost_item",
    "price_list_block",
    "provenance_of",
]
