# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the assemblies module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.assemblies",
    entities=(
        Entity("Assembly", label="data_paths.entity.assembly"),
        Entity("AssemblyTemplate", label="data_paths.entity.assembly_template"),
        Entity("Component", label="data_paths.entity.component"),
    ),
    inputs=(
        DataPath(
            "oe_catalog", "Component", via="Component.catalog_resource_id", label="data_paths.entity.catalog_resource"
        ),
        DataPath("oe_costs", "Component", via="Component.cost_item_id", label="data_paths.entity.cost_item"),
    ),
)
