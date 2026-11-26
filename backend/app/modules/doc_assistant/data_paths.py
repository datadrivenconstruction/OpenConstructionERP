# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the doc_assistant module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.doc_assistant",
    entities=(Entity("SavedAnswer", label="data_paths.entity.saved_answer"),),
    reason="No foreign key joins its tables to another module's tables; reads code of ai, contracts, correspondence, documents, file_search, meetings and 2 more",
)
