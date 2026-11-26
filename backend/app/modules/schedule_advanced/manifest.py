# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Advanced module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.schedule_advanced.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_schedule_advanced",
    version="0.1.0",
    display_name="Schedule Advanced (Last Planner)",
    description=(
        "LPS: phase plans, look-ahead, constraints, weekly work plans, "
        "commitments, PPC + RNC, baselines + delta tracking"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
