# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost-match module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.cost_match.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_cost_match",
    version="1.0.0",
    display_name="Cost Match",
    description=(
        "Match free-text bill-of-quantities lines against a cost base and "
        "review the suggestions: every line lands in one of four tiers by "
        "confidence, and a person confirms, overrides or rejects each one."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_costs", "oe_dashboards"],
    optional_depends=["oe_ai"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
