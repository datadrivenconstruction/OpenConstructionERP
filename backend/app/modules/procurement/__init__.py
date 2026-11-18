# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement module - purchase orders, goods receipts, vendor management."""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.procurement.permissions import register_procurement_permissions

    register_procurement_permissions()

    from app.core.doc_templates.layout.spec import register_layout_provider
    from app.modules.procurement.layouts import register_procurement_layouts

    register_layout_provider(register_procurement_layouts)
