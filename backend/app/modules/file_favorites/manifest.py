# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Favourites / Pin module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.file_favorites.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_file_favorites",
    version="1.0.0",
    display_name="File Favourites",
    description=(
        "Per-user star + pin for the 8 file-manager kinds. Favourites are "
        "personal bookmarks; pins are elevated favourites that always sort "
        "first in the user's Recently Viewed strip."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
