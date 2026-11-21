# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_i18n_foundation."""

from app.core.module_loader import ModuleManifest
from app.modules.i18n_foundation.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_i18n_foundation",
    version="0.1.0",
    display_name="Internationalization Foundation",
    description="Multi-currency exchange rates, country registry, work calendars, tax configurations",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
