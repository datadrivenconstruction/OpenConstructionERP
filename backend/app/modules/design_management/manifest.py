# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design management module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.design_management.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_design_management",
    version="0.1.0",
    display_name="Design management",
    description=(
        "Owner-side design steering: one project breakdown structure, design roles and approval points, "
        "a design schedule per phase, drawing numbering as data, the drawing register on CDE, the "
        "distribution matrix and releases as transmittals, internal reviews, expert reports and the "
        "permit design package"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_cde holds every drawing and report (numbers, revisions, states);
    # oe_transmittals records every issue; oe_project_governance owns the
    # catalogue store, the phase model and the gate readiness this module
    # feeds; oe_approval_routes decides approval points and releases.
    depends=[
        "oe_users",
        "oe_projects",
        "oe_cde",
        "oe_transmittals",
        "oe_file_distribution",
        "oe_review_authority",
        "oe_approval_routes",
        "oe_project_governance",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
