# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-inventory module (on-site material metering and stock).

Tracks materials from the moment they arrive on site (a procurement goods
receipt) through installation against a BoQ position, waste and shrinkage, and
transfers between storage locations. Stock on hand is never stored: it is derived
as the signed sum of movements by the pure ledger in
:mod:`app.modules.site_inventory.ledger`, which also computes inventory turnover
and days on hand, the waste ratio, and material-cost variance against the
estimate.
"""


async def on_startup() -> None:
    """Module startup hook - register the read/write permissions."""
    from app.modules.site_inventory.permissions import register_site_inventory_permissions

    register_site_inventory_permissions()

    from app.modules.site_inventory.validators import register_site_inventory_validation_rules

    register_site_inventory_validation_rules()
