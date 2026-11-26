# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the project_tax module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.project_tax",
    entities=(Entity("ProjectTaxProfile", label="data_paths.entity.project_tax_profile"),),
    reason="No foreign key joins its tables to another module's tables",
)
