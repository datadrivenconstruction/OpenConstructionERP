from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_backup",
    version="1.0.0",
    display_name="Backup & Restore",
    description="Export and import user data backups",
    author="OpenEstimate Core Team",
    category="core",
    depends=[],
    auto_install=True,
)
