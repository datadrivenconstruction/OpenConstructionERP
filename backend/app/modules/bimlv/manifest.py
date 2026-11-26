# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM-LV container module manifest (DIN SPEC 91350)."""

from app.core.module_loader import ModuleManifest
from app.modules.bimlv.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_bimlv",
    version="0.1.0",
    display_name="BIM-LV Container",
    description=(
        "Read and write DIN SPEC 91350 BIM-LV containers: bundle a GAEB LV with "
        "its IFC/BIM model reference and the position-to-element link table, and "
        "materialize the links onto existing BOQ positions and BIM elements"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_boq", "oe_bim_hub"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
