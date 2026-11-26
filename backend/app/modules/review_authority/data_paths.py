# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the review_authority module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.review_authority",
    entities=(
        Entity("ReviewCycle", label="data_paths.entity.review_cycle"),
        Entity("Remark", label="data_paths.entity.remark"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of credentials",
)
