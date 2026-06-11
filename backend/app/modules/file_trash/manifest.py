# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Recycle Bin module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_trash",
    version="1.0.0",
    display_name="Recycle Bin",
    description=(
        "Centralised soft-delete + restore for the 8 file-manager kinds. "
        "Trashed rows are snapshot to oe_file_trash and the original row "
        "is removed; restore re-creates the row in its kind table. A "
        "configurable retention window (default 30 days) drives a nightly "
        "hard-purge job."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)
