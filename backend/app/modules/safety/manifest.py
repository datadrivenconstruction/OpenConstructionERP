# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Safety module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.safety.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_safety",
    version="0.1.0",
    display_name="Safety Management",
    description="Safety incident reporting and observation tracking with risk scoring, corrective actions, and regulatory compliance",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
