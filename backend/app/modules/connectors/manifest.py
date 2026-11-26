# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Connectors module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.connectors.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_connectors",
    version="0.1.0",
    display_name="Document Connectors",
    description=(
        "Pull documents that live in scattered places into the project record. Point a connector "
        "at a watched folder and a sync brings each new file in as a first-class, searchable "
        "project document, deduplicated so the same file is never imported twice"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_documents"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
