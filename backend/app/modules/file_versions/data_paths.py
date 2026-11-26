# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_versions module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_versions",
    entities=(Entity("FileVersion", label="data_paths.entity.file_version"),),
    outputs=(
        DataPath(
            "oe_file_comments", "FileComment", via="FileComment.file_version_id", label="data_paths.entity.file_comment"
        ),
        DataPath("oe_markups", "Markup", via="Markup.file_version_id", label="data_paths.entity.markup"),
    ),
)
