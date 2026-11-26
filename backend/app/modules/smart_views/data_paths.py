# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the smart_views module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.smart_views",
    entities=(Entity("SmartView", label="data_paths.entity.smart_view"),),
    reason="No foreign key joins its tables to another module's tables; subscribes to projects.project.updated; publishes smart_views.visibility_changed; reads code of bim_hub",
)
