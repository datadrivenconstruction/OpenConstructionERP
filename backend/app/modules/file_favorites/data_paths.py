# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_favorites module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_favorites",
    roles=("project_manager",),
    duties=(Duty("project_manager", "data_paths.duty.file_favorites.project_manager"),),
    entities=(Entity("FileFavorite", label="data_paths.entity.file_favorite", route="/files"),),
)
