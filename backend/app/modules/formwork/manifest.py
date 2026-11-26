# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Formwork module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.formwork.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_formwork",
    version="1.0.0",
    display_name="Formwork",
    description=(
        "Formwork system catalogue with a two-part rate build-up (amortising panel cost plus "
        "per-use erect and strike), per-BOQ assignments that re-price whenever the catalogue "
        "moves, pour-cycle scheduling that derives the reuse count and checks the striking "
        "time, a project rollup showing what the reuse assumption is worth, and eleven "
        "validation rules over the whole thing"
    ),
    author="OpenConstructionERP Core Team",
    category="estimation",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
