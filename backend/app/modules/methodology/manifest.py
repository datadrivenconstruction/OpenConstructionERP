# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimating-methodology module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.methodology.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_methodology",
    version="0.1.0",
    display_name="Estimating Methodologies",
    description=(
        "Data-driven per-country estimating methodology engine: typed BOQ "
        "hierarchies, analytical dimensions, cascading markups and country / "
        "industry templates that coexist with the international method."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
