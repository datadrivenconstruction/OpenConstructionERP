# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cases module manifest."""

from app.core.data_paths import DataPaths
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_cases",
    version="1.0.0",
    display_name="Cases",
    description=(
        "User-authored case scenarios. The shipped playbooks are source files "
        "compiled into the frontend; this module lets a team write its own "
        "walkthrough of how work is done here, start one from any shipped "
        "playbook, and pin a curated set to a project so the selection belongs "
        "to the account rather than to one browser."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DataPaths(reason="User-authored walkthroughs; they reference no project records"),
)
