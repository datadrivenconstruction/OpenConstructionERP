# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the markups module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.markups",
    entities=(
        Entity("StampTemplate", label="data_paths.entity.stamp_template"),
        Entity("Markup", label="data_paths.entity.markup"),
        Entity("ScaleConfig", label="data_paths.entity.scale_config"),
        Entity("MarkupComment", label="data_paths.entity.markup_comment"),
    ),
    inputs=(
        DataPath("oe_file_versions", "Markup", via="Markup.file_version_id", label="data_paths.entity.file_version"),
    ),
)
