# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project handbook module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.project_handbook.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_project_handbook",
    version="0.1.0",
    display_name="Project handbook",
    description=(
        "Project handbook with a chapter catalogue, owners, versions and four-eyes approval per chapter, "
        "live links to the records of the other modules, a PDF of the whole handbook, and the data room: "
        "the governance folder tree materialised into the project's document folders"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store, the phase model whose folders the data room
    # materialises and the four-eyes setting; oe_documents owns the folders and the documents in them.
    depends=["oe_users", "oe_projects", "oe_project_governance", "oe_documents"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
