# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the allowances module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.allowances",
    entities=(
        Entity("Allowance", label="data_paths.entity.allowance"),
        Entity("AllowanceDrawdown", label="data_paths.entity.allowance_drawdown"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq",
)
