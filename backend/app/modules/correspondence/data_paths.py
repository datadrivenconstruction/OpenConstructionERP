# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the correspondence module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.correspondence",
    entities=(Entity("Correspondence", label="data_paths.entity.correspondence"),),
    reason="No foreign key joins its tables to another module's tables; publishes correspondence.created, correspondence.deleted, correspondence.updated; reads code of rfi",
)
