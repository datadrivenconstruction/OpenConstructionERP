# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Product & Resource Catalog module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.catalog.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_catalog",
    version="0.1.0",
    display_name="Product & Resource Catalog",
    description="Curated catalog of materials, equipment, labor, and operators extracted from cost databases",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_costs"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
