# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Commitment release module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.commitment_release.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_commitment_release",
    version="0.1.0",
    display_name="Commitment release",
    description=(
        "Commitment and release matrix: per commitment the amount, cost bearer, approver tier, "
        "preconditions, latest decision date and the residual loss on abort, under a "
        "delegation-of-authority schedule"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store this module's schedules
    # live in and the gate readiness it feeds; oe_approval_routes decides who
    # may release; costmodel holds the one commitment counting rule.
    depends=["oe_users", "oe_projects", "oe_approval_routes", "oe_project_governance", "oe_costmodel"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
