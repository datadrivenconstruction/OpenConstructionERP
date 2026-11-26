# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design Options module manifest.

Generate and compare alternative design options for a project side by side. The
module depends on projects and the BOQ editor (each option gets its own priced
bill of quantities) and optionally reuses the BIM hub, element matching, cost
databases, the 5D cost model, reporting and tendering when those are installed.
"""

from app.core.module_loader import ModuleManifest
from app.modules.design_options.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_design_options",
    version="0.1.0",
    display_name="Design Options",
    description=(
        "Generate and compare alternative design options side by side. Each option "
        "pairs a source model or document with its own priced bill of quantities, so "
        "the team can weigh a full set of options on total cost, by-trade deltas and "
        "cost per m2, pick a baseline and get a fairness-checked recommendation before "
        "committing to one."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    optional_depends=[
        "oe_bim_hub",
        "oe_match_elements",
        "oe_costs",
        "oe_costmodel",
        "oe_reporting",
        "oe_tendering",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
