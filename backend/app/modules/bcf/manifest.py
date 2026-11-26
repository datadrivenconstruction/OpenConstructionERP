# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BCF (BIM Collaboration Format) module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.bcf.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_bcf",
    version="1.0.0",
    display_name="BCF Issues & Viewpoints",
    description=(
        "Server-backed BCF 2.1 / 3.0 issue tracking: persistent topics, "
        "comments and viewpoints with full .bcfzip import/export roundtrip."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
