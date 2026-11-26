# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Transmittals module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.transmittals.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_transmittals",
    version="0.1.0",
    display_name="Transmittals",
    description="Formal document transmittal management with recipients, acknowledgements, and responses",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
