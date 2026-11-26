# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the win_loss module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.win_loss",
    entities=(Entity("BidOutcome", label="data_paths.entity.bid_outcome"),),
    reason="No foreign key joins its tables to another module's tables",
)
