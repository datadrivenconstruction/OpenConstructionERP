# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Off-site / Prefab / DfMA module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.prefab.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_prefab",
    version="1.0.0",
    display_name="Off-site / Prefab / DfMA",
    description=(
        "Design for Manufacture and Assembly register - track off-site "
        "manufactured units (pods, panels, volumetric modules, skids) through "
        "an ordered production lifecycle from design to installation, with a "
        "hard quality gate before anything is dispatched, delivered or installed."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
