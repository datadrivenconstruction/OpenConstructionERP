# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the catalog module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.catalog",
    entities=(Entity("CatalogResource", label="data_paths.entity.catalog_resource"),),
    outputs=(
        DataPath(
            "oe_assemblies", "Component", via="Component.catalog_resource_id", label="data_paths.entity.component"
        ),
    ),
)
