# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_trash module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_trash",
    roles=("project_manager",),
    duties=(Duty("project_manager", "data_paths.duty.file_trash.project_manager"),),
    entities=(Entity("FileTrash", label="data_paths.entity.trashed_file", route="/files/trash"),),
)
