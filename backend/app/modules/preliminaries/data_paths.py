# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the preliminaries module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.preliminaries",
    entities=(Entity("PrelimItem", label="data_paths.entity.prelim_item"),),
    reason="No foreign key joins its tables to another module's tables",
)
