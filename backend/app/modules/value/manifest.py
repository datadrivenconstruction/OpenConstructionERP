# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Value Realized module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.value.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_value",
    version="0.1.0",
    display_name="Value Realized",
    description=(
        "Composition layer that turns figures the platform already computes - "
        "approved-change cost and schedule exposure, the cost-recovery ledger, "
        "and admin hours given back by assisted actions - into a single project "
        "and portfolio value-realized summary, plus an adoption-vs-non-adoption "
        "benchmark on the firm's own projects. It reads the existing change, "
        "recovery and activity records; its only table is a small admin-tunable "
        "lookup of the hours-saved minute factors (oe_value_time_factor)"
    ),
    author="OpenConstructionERP Core Team",
    category="controls",
    depends=[
        "oe_users",
        "oe_projects",
        "oe_changeorders",
        "oe_variations",
        "oe_moc",
        "oe_cost_recovery",
        "oe_change_intelligence",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
