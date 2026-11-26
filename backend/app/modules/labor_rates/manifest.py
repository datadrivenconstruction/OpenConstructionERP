# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Labor rates module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.labor_rates.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_labor_rates",
    version="0.1.0",
    display_name="Labor & Crew Rates",
    description=(
        "All-in labor rate build-up from a base wage plus configurable on-costs "
        "(statutory charges, insurance, leave, overtime, supervision, small tools), "
        "and composite crew rates blending several trades."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
