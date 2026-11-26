# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the retrieval module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.retrieval",
    entities=(Entity("SavedSearch", label="data_paths.entity.saved_search"),),
    reason="No foreign key joins its tables to another module's tables; reads code of changeorders, correspondence, documents",
)
