# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the collaboration_locks module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.collaboration_locks",
    entities=(Entity("CollabLock", label="data_paths.entity.collab_lock"),),
    reason="No foreign key joins its tables to another module's tables; reads code of bim_hub, boq, changeorders, documents, inspections, meetings and 10 more",
)
