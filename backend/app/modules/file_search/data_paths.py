# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_search module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_search",
    entities=(Entity("FileSearchIndex", label="data_paths.entity.file_search_index"),),
    reason="No foreign key joins its tables to another module's tables; subscribes to documents.document.deleted; reads code of documents",
)
