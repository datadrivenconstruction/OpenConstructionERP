# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the list_views module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.list_views",
    roles=("project_manager",),
    duties=(Duty("project_manager", "data_paths.duty.list_views.project_manager"),),
    entities=(Entity("ListView", label="data_paths.entity.list_view"),),
)
