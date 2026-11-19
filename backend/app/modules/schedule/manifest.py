# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""4D Schedule module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.schedule.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_schedule",
    version="0.1.0",
    display_name="4D Schedule",
    description="4D construction scheduling - linking BOQ positions to a timeline",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
