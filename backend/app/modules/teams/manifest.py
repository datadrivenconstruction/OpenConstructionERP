# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Team Visibility module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.teams.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_teams",
    version="0.1.0",
    display_name="Team Visibility",
    description="Team-based entity visibility and access control within projects",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
