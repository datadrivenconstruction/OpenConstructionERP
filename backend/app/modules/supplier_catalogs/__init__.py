# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Supplier Catalogs & Vendor Management module.

Extends procurement with:
    - Vendor master + contacts
    - Item categories + catalog items
    - Vendor price lists, imported from Excel/CSV/SAP exports with a preview
    - Contractor discount agreements and net prices
    - Purchase requisitions with approval chain
    - Extended POs (linked to PRs and contracts)
    - Goods receipts with batch/serial tracking and stock posting
    - Vendor invoices + 3-way match (PO ↔ GR ↔ Invoice)
    - Warehouses + stock balances + stock movements
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and notification subscribers."""
    from app.modules.supplier_catalogs.events import register_subscribers
    from app.modules.supplier_catalogs.permissions import (
        register_supplier_catalogs_permissions,
    )
    from app.modules.supplier_catalogs.validators import register_supplier_catalogs_rules

    register_supplier_catalogs_permissions()
    register_supplier_catalogs_rules()
    register_subscribers()
