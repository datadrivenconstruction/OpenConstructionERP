# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Saved Views module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.file_saved_views.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_file_saved_views",
    version="1.0.0",
    display_name="File Saved Views",
    description=(
        "Personal & shared smart-folder views for /files - serialise the "
        "current filter (kind, query, sort, extension, tags, date range, "
        "custom keys) under a name and re-apply it with one click."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
