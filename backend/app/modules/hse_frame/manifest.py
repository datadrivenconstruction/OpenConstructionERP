# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE frame module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.hse_frame.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_hse_frame",
    version="0.1.0",
    display_name="HSE frame",
    description=(
        "The health, safety and environment frame of a project: requirements on designers and "
        "contractors, environmental review, site clearances, permit conditions merged from the permits "
        "module, energy, climate and sustainability targets, safety coordination with appointed roles, "
        "the health and safety plan and the security concept. National duties are catalogue data; "
        "incidents, permits to work, audits and inspections stay in their own modules and are linked."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # Records stay in their owning modules (permits, safety, hse_advanced, construction_control) and
    # are only linked and read when those modules are installed; none of them is required.
    depends=["oe_users", "oe_projects", "oe_project_governance"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
