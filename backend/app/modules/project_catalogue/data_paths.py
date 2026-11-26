# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the project_catalogue module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.project_catalogue",
    entities=(Entity("ProjectCatalogueItem", label="data_paths.entity.project_catalogue_item"),),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, catalog, costs",
)
