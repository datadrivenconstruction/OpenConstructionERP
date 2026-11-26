# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Permits module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.permits.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_permits",
    version="0.1.0",
    display_name="Authority permits",
    description=(
        "Permit roadmap (which authority approvals, who applies, when, in what order, statutory clocks) "
        "and the consolidated register of every permit condition with owner, trigger, evidence and discharge"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store the permit types live in and the
    # gate readiness this module feeds; oe_approval_routes runs the optional internal
    # release before submission; schedule supplies needed-by dates and the calendar.
    depends=["oe_users", "oe_projects", "oe_approval_routes", "oe_project_governance", "oe_schedule"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
