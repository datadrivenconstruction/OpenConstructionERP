# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Takeoff module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest
from app.modules.takeoff.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_takeoff",
    version="0.1.0",
    display_name="Quantity Takeoff",
    description="Manual and AI-assisted quantity takeoff from drawings and models",
    author="OpenConstructionERP Core Team",
    category="extension",
    depends=["oe_projects", "oe_cad"],
    auto_install=False,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CALLS_MODEL,
        what=(
            "A rasterised drawing page into proposed measurements: a hosted vision model proposes a "
            "scale reference, room polygons and symbol positions, which this module then recomputes "
            "as checked geometry"
        ),
        basis=(
            "The vision call goes through oe_ai. The offline detector in raster_recognize.py is not "
            "part of this claim and is rule-based - OpenCV thresholds and contours, no trained model "
            "anywhere in it - and it is declared here so that reading the module as one thing does "
            "not attribute the model to the half that has none. Both paths return candidates a human "
            "confirms, and plan_read.py owns every number the model is not trusted to produce"
        ),
    ),
    data_paths=DATA_PATHS,
)
