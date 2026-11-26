# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from app.core.module_loader import ModuleManifest
from app.modules.backup.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_backup",
    version="1.0.0",
    display_name="Backup & Restore",
    description="Export and import user data backups",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    data_paths=DATA_PATHS,
)
