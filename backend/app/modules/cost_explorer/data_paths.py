# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cost_explorer module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.cost_explorer",
    entities=(Entity("CostItemResource", label="data_paths.entity.cost_item_resource"),),
    reason="No foreign key joins its tables to another module's tables; subscribes to costs.item.created, costs.item.deleted, costs.item.updated, costs.items.bulk_imported; reads code of catalog, costs",
)
