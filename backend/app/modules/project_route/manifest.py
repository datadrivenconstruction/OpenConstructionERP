# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Work-type classifier gate module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.project_route.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_project_route",
    version="0.1.0",
    display_name="Work-type Route Classifier",
    description=(
        "Classifies a project's work type - new build, reconstruction, "
        "capital repair, re-equipment, maintenance, demolition, change of use "
        "- plus a few classifier answers into a delivery / permit route: full "
        "permit, notification, permitted development, exempt or expertise "
        "required. The decision tree is jurisdiction-neutral data that regional "
        "packs override; a confirmed route gates the project before it proceeds."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
