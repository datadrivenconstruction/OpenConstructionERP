# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""5D Cost Model module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.costmodel.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_costmodel",
    version="0.1.0",
    display_name="5D Cost Model",
    description=(
        "5D cost management - S-curves, cash flow projections, earned value analysis (EVM), and budget tracking"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
