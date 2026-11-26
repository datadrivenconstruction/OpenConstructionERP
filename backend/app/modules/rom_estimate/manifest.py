# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Conceptual (ROM) estimate module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.rom_estimate.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_rom_estimate",
    version="0.1.0",
    display_name="Conceptual Estimate",
    description=(
        "Instant order-of-magnitude estimate from building type, gross floor area, "
        "quality and region - an elemental cost per m2 model with an honest accuracy band"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_costmodel"],
    display_name_i18n={"de": "Grobkostenschätzung", "ru": "Концептуальная оценка"},
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
