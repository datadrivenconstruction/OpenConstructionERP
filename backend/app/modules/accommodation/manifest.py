# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accommodation module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.accommodation.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_accommodation",
    version="0.1.0",
    display_name="Accommodation",
    description=(
        "Unified housing module: worker camps, rental apartments, and hotels. "
        "Rooms, bookings, charges. Optional one-click bootstrap from a PropDev "
        "block and HR-driven room suggestion."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
