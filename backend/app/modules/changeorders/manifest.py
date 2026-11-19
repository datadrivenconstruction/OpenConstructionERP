# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change Orders module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.changeorders.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_changeorders",
    version="0.1.0",
    display_name="Change Orders",
    description="Track scope changes, cost impacts, and approval workflows",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
