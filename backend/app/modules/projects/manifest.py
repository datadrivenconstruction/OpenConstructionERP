# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Projects module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.projects.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_projects",
    version="0.1.0",
    display_name="Projects",
    description="Project management with regional settings, classification standards, and validation configuration",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
