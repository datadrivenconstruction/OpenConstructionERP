# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Staffing module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.staffing.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_staffing",
    version="0.1.0",
    display_name="Staffing",
    description=(
        "Project staffing plan for development, execution and operation: roles, entry dates, recruiting "
        "status, owner organisation, consultants, operator build-up and knowledge handover; plus the personnel "
        "file of each person on the project with document expiry, travel, leave and retention"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store, the gate that approves the
    # plan and the frame document that carries it; teams owns the person
    # (RosterMember), credentials the validity of every document,
    # accommodation the beds.
    depends=["oe_users", "oe_projects", "oe_project_governance", "oe_teams", "oe_credentials", "oe_accommodation"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
