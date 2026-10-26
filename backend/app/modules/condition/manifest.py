# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Condition module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_condition",
    version="0.1.0",
    display_name="Condition & Maintenance Plan",
    description=(
        "Condition ratings per asset or element on a configurable scale (severity, extent, "
        "intensity), recorded during inspections, and a multi-year maintenance plan derived "
        "from them: actions, intervals, unit costs, year buckets, inflation from the price "
        "index, present value, written back to the asset register for whole-life cost"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    optional_depends=["oe_inspections", "oe_bim_hub", "oe_price_index", "oe_carbon"],
    auto_install=True,
    enabled=True,
)
