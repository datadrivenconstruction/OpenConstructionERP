# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the resource_summary module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.resource_summary",
    entities=(Entity("ResourceStatementSnapshot", label="data_paths.entity.resource_statement_snapshot"),),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, price_breakdown, procurement",
)
