# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Users & authentication module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.users.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_users",
    version="0.1.0",
    display_name="Users & Authentication",
    description="User management, JWT authentication, API keys, and RBAC",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
