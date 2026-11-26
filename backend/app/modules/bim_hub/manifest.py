# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM Hub module manifest - BIM data management backend."""

from app.core.module_loader import ModuleManifest
from app.modules.bim_hub.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_bim_hub",
    version="0.1.0",
    display_name="BIM Hub",
    description="BIM data management: models, elements, BOQ linking, quantity maps, and model diffs",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
