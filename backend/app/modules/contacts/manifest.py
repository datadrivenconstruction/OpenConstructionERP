# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contacts Directory module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.contacts.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_contacts",
    version="0.1.0",
    display_name="Contacts Directory",
    description="Unified contacts directory for clients, subcontractors, suppliers, consultants",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
