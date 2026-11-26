# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Equipment & Fleet Management module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.equipment.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_equipment",
    version="0.1.0",
    display_name="Equipment & Fleet Management",
    description=(
        "Owned/rented equipment fleet with telemetry, maintenance scheduling, inspections, internal rental billing"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
