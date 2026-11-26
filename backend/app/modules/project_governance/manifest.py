# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project governance module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.project_governance.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_project_governance",
    version="0.1.0",
    display_name="Project governance",
    description=(
        "Phase model with gates: management areas with owners, frame documents that become "
        "binding at a gate, readiness checks, immutable gate decisions with conditions"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_approval_routes decides who may sign a gate off; oe_cde holds the
    # frame document revisions. Both are read, never written, except the
    # approval instance this module starts and closes for its own gates.
    depends=["oe_users", "oe_projects", "oe_approval_routes", "oe_cde"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
