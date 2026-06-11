# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Versioning module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_versions",
    version="1.0.0",
    display_name="File Versioning",
    description=(
        "Polymorphic version chains across all 8 file kinds with "
        "restore-any-version semantics. A re-upload of the same canonical "
        "name within a project flips the old row to superseded and "
        "promotes the new row to current."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)
