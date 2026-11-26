# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the reconciliation module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.reconciliation",
    entities=(Entity("RecordLink", label="data_paths.entity.record_link"),),
    reason="No foreign key joins its tables to another module's tables; reads code of changeorders, correspondence, moc, variations",
)
