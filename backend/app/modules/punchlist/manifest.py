# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Punch List module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.punchlist.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_punchlist",
    version="0.1.0",
    display_name="Punch List",
    description="Track construction deficiencies, quality issues, and snag items with photo evidence and verification workflows",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
