# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost recovery module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.cost_recovery.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_cost_recovery",
    version="0.1.0",
    display_name="Cost Recovery",
    description=(
        "Records back-charges - costs the project intends to recover from the "
        "party responsible for causing them (rework from a subcontractor defect, "
        "extra cost from a supplier delay) - and rolls them up into a per-party "
        "and per-currency recovery ledger showing what is chargeable, what has "
        "been recovered and what is still outstanding against whom."
    ),
    author="OpenConstructionERP Core Team",
    category="controls",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
