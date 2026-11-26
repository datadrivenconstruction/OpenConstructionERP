# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the geo_hub module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.geo_hub",
    entities=(
        Entity("GeoAnchor", label="data_paths.entity.geo_anchor"),
        Entity("GeoOverlay", label="data_paths.entity.geo_overlay"),
        Entity("GeoRasterOverlay", label="data_paths.entity.geo_raster_overlay"),
        Entity("GeoViewpoint", label="data_paths.entity.geo_viewpoint"),
    ),
    inputs=(
        DataPath("oe_pointcloud", "SurveyCapture", via="SurveyCapture.scan_id", label="data_paths.entity.scan_dataset"),
        DataPath(
            "oe_schedule", "SurveyObservation", via="SurveyObservation.activity_id", label="data_paths.entity.activity"
        ),
    ),
)
