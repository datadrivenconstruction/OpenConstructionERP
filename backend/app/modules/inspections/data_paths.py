# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the inspections module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.inspections",
    entities=(Entity("QualityInspection", label="data_paths.entity.quality_inspection"),),
    reason="No foreign key joins its tables to another module's tables; subscribes to site_sensors.strip.struck; reads code of ncr, punchlist, site_sensors",
)
