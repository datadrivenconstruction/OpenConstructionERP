# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFI module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.rfi.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_rfi",
    version="0.1.0",
    display_name="Requests for Information",
    description="RFI management - questions, responses, cost/schedule impact tracking, and drawing cross-references",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
