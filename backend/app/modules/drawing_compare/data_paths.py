# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the drawing_compare module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.drawing_compare",
    entities=(
        Entity("DrawingComparison", label="data_paths.entity.drawing_comparison"),
        Entity("DrawingChange", label="data_paths.entity.drawing_change"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, documents, dwg_takeoff, markups, rfi, takeoff",
)
