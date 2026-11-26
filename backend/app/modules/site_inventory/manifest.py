# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-inventory module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.site_inventory.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_site_inventory",
    version="1.0.0",
    display_name="Site Inventory",
    description=(
        "On-site material metering and stock: a movement ledger (inbound, "
        "consumption against a BoQ position, waste and shrinkage, inter-location "
        "transfer) that derives stock on hand, inventory turnover and days on "
        "hand, the waste ratio, and material-cost variance against the estimate. "
        "Closes the loop between procurement goods receipts and what is actually "
        "held and consumed on site."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Hard deps supply the tables this module foreign-keys into: projects (scope),
    # BoQ (consumption + budget), procurement (goods receipts + requisition lines).
    depends=["oe_projects", "oe_boq", "oe_procurement"],
    # Progress and costs enrich the reports where present but are not required for
    # the ledger to work, so they stay optional.
    optional_depends=["oe_progress", "oe_costs"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
