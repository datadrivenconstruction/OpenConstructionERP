# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field Reports module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.fieldreports.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_fieldreports",
    version="0.1.0",
    display_name="Field Reports",
    description="Daily field reports for construction sites - weather, workforce, delays, safety incidents, and approvals",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
