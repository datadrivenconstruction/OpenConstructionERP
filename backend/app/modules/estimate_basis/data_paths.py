# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the estimate_basis module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.estimate_basis",
    entities=(Entity("EstimateBasis", label="data_paths.entity.estimate_basis"),),
    reason="No foreign key joins its tables to another module's tables; reads code of allowances, boq, costs, preliminaries",
)
