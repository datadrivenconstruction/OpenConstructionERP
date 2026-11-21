# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_saved_views module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_saved_views",
    roles=("project_manager",),
    duties=(Duty("project_manager", "data_paths.duty.file_saved_views.project_manager"),),
    entities=(Entity("FileSavedView", label="data_paths.entity.saved_view", route="/files"),),
)
