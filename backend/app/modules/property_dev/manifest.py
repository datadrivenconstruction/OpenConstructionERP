# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Property Development module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.property_dev.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_property_dev",
    version="0.1.0",
    display_name="Property Development",
    description=(
        "Property development + buyer portal: developments, plots, house types, "
        "options, buyer selections, freeze deadlines, handover & snagging, "
        "warranty claims"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
