# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plant register module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.plant_register.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_plant_register",
    version="0.1.0",
    display_name="Plant register",
    description=(
        "Main components and long-lead items: lead time with the date of enquiry, latest order date, "
        "capacity reservation, procurement route, delivery limits and the spares concept"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store, the plant area owner and
    # the gate readiness this register feeds; oe_approval_routes approves the
    # decision papers; oe_site_logistics holds the site plant positions.
    depends=["oe_users", "oe_projects", "oe_approval_routes", "oe_project_governance", "oe_site_logistics"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
