# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Correspondence module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.correspondence.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_correspondence",
    version="0.1.0",
    display_name="Correspondence",
    description="Project correspondence tracking - letters, emails, notices, memos and reports with direction, contacts, and document cross-references",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
