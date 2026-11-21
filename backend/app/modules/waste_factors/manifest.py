# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Waste Factors module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.waste_factors.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_waste_factors",
    version="0.1.0",
    display_name="Waste Factors",
    description="Net-to-gross quantity adjustment with waste, lap and coverage factors",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
