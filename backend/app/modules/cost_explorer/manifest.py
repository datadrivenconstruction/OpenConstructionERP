# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Cost Explorer module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.cost_explorer.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_cost_explorer",
    version="1.0.0",
    display_name="Cost Explorer",
    description=(
        "A search-first workspace over the cost and resource databases. Find "
        "priced work by the resources it consumes, search the catalogs, compare "
        "the same scope across regional price bases, and substitute resources to "
        "test the effect on a rate. Built on a resource to work reverse index "
        "over each cost item's resource composition."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Reads the cost items (oe_costs) and the resource catalog (oe_catalog).
    # Declared as hard dependencies so the load order is correct and neither can
    # be disabled while the reverse index still mirrors their rows.
    depends=["oe_costs", "oe_catalog"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
