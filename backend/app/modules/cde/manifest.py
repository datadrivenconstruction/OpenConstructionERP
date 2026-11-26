# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CDE module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.cde.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_cde",
    version="0.1.0",
    display_name="Common Data Environment (ISO 19650)",
    description="ISO 19650 compliant Common Data Environment - document containers, revisions, state transitions, and suitability codes",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_documents"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
