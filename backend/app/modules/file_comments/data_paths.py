# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_comments module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_comments",
    entities=(
        Entity("FileComment", label="data_paths.entity.file_comment"),
        Entity("FileCommentMention", label="data_paths.entity.file_comment_mention"),
    ),
    inputs=(
        DataPath(
            "oe_file_versions", "FileComment", via="FileComment.file_version_id", label="data_paths.entity.file_version"
        ),
    ),
)
