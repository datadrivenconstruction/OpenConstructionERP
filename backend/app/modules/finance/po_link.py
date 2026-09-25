# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which purchase order a supplier invoice bills against.

The link has two spellings and every reader has to accept both.
``Invoice.purchase_order_id`` is the column. Before it existed,
``POST /procurement/{po_id}/create-invoice/`` recorded the same fact as
``metadata_["po_id"]``, and those rows keep only the stamp: production gains
the column on boot through the schema heal, which adds columns and never
backfills them. A reader that looked at the column alone would silently lose
every order-created invoice raised before the upgrade.
"""

from __future__ import annotations

import uuid


def invoice_po_link(purchase_order_id: object, metadata: object) -> uuid.UUID | None:
    """Return the purchase order an invoice is linked to, or ``None``.

    Args:
        purchase_order_id: The invoice's ``purchase_order_id`` column value.
        metadata: The invoice's ``metadata_`` JSON, read for the legacy
            ``po_id`` stamp when the column is empty.

    Returns:
        The linked order id; the column wins when both are present.
    """
    for raw in (purchase_order_id, metadata.get("po_id") if isinstance(metadata, dict) else None):
        if raw is None or raw == "":
            continue
        if isinstance(raw, uuid.UUID):
            return raw
        try:
            return uuid.UUID(str(raw))
        except (ValueError, TypeError):
            continue
    return None
