# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the photos module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.photos",
    entities=(
        Entity("PhotoAlbum", label="data_paths.entity.photo_album"),
        Entity("PhotoCompare", label="data_paths.entity.photo_compare"),
        Entity("PhotoAISuggestion", label="data_paths.entity.photo_ai_suggestion"),
        Entity("PhotoLink", label="data_paths.entity.photo_link"),
    ),
    inputs=(
        DataPath(
            "oe_documents", "PhotoAlbum", via="PhotoAlbum.cover_photo_id", label="data_paths.entity.project_photo"
        ),
    ),
)
