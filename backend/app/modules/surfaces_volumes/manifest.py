# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surfaces and volumes module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.surfaces_volumes.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_surfaces_volumes",
    version="0.1.0",
    display_name="Surfaces & Volumes",
    description=(
        "Ground surfaces from survey points or LandXML, and cut and fill between two of them by grid, "
        "triangle prisms or average end area, with coverage and a confidence score. A surveyor confirms "
        "the result before it feeds a BOQ line or a progress entry; both carry a source trail and the "
        "volume report prints the method, the coordinate system and who signed it off."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_survey_core"],
    optional_depends=["oe_boq", "oe_progress", "oe_pointcloud", "oe_contracts"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
