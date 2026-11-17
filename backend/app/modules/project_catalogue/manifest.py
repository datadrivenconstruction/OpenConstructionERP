# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_project_catalogue",
    version="0.1.0",
    display_name="Project Catalogue",
    description=(
        "A project's own set of rates and resources, copied from the cost database or the company "
        "library and edited for this job without touching the master data. Each copy keeps its "
        "source, shows when the source price moves, and lets the estimator take the new price or "
        "keep the local one. Bill lines priced from it can be refreshed in one step."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_costs", "oe_boq"],
    optional_depends=["oe_catalog"],
    auto_install=True,
    enabled=True,
)
