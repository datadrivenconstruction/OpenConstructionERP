# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Notifications module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.notifications.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_notifications",
    version="0.1.0",
    display_name="Notifications",
    description="In-app notification system with i18n keys and per-user preferences",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
