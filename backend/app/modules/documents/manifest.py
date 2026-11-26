# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Documents module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.documents.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_documents",
    version="0.1.0",
    display_name="Documents",
    description="Upload, categorize, and manage project documents with tagging and search",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
