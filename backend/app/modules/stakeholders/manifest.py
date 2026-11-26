# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stakeholders module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.stakeholders.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_stakeholders",
    version="0.1.0",
    display_name="Stakeholders and organisation",
    description=(
        "Stakeholder register with assessments, communication plan, engagement events and commitments "
        "to stakeholders; project roles, governance bodies and the mandate matrix of who decides what"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store the frameworks live in and
    # the gate readiness this module feeds; oe_approval_routes runs commitment
    # approvals; oe_teams holds the roster role holders point at; oe_contacts
    # holds the people and organisations a stakeholder refers to.
    depends=["oe_users", "oe_projects", "oe_teams", "oe_contacts", "oe_approval_routes", "oe_project_governance"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
