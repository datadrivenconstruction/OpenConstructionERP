# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Engineering brief module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.engineering_brief.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_engineering_brief",
    version="0.1.0",
    display_name="Engineering brief",
    description=(
        "Project definition for engineering and scheduling: the requirements brief with structured "
        "requirements, the technical concept, the area and quantity programme and the framework schedule "
        "whose milestones are bound to the gates of the project's governance model"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store, the gate that approves the brief and the frame
    # document that carries it; oe_requirements holds the requirements themselves; oe_schedule holds the
    # programme the framework schedule is published into.
    depends=["oe_users", "oe_projects", "oe_project_governance", "oe_requirements", "oe_schedule"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
