# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk Register module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.risk.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_risk",
    version="0.1.0",
    display_name="Risk Register",
    description="Track project risks, assess probability and impact, manage mitigation strategies",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
