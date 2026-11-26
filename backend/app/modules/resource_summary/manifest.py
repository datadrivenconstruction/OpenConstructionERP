# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Resource Summary module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.resource_summary.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_resource_summary",
    version="1.0.0",
    display_name="Resource Summary",
    description=(
        "Rolls up the resource split stored on every priced position across the "
        "whole estimate into one procurement-ready statement: total labour-hours "
        "and cost, and the total quantity and cost of each material, machine and "
        "subcontract line. Gives buyers a single schedule of what the estimate "
        "implies they must procure. Reads the existing per-position splits; adds "
        "no new estimating data."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # Reads BoQ positions (their stored resource split) read-only.
    depends=["oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
