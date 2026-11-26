# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resources module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.resources.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_resources",
    version="0.1.0",
    display_name="Resource Planning",
    description=(
        "Resources (people/crews/equipment/subs) with skills, certifications, "
        "availability, assignments, conflict detection, skill-based matching"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
