# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Comments & Viewpoints module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.collaboration.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_collaboration",
    version="0.1.0",
    display_name="Comments & Viewpoints",
    description="Threaded comments with @mentions and viewpoints for any entity",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
