# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_tags module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_tags",
    entities=(
        Entity("FileTag", label="data_paths.entity.file_tag"),
        Entity("FileTagAssignment", label="data_paths.entity.file_tag_assignment"),
    ),
    reason="No foreign key joins its tables to another module's tables",
)
