# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the resumable_uploads module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.resumable_uploads",
    entities=(Entity("ResumableUploadSession", label="data_paths.entity.resumable_upload_session"),),
    reason="No foreign key joins its tables to another module's tables; reads code of documents",
)
