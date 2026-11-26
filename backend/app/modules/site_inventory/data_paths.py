# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the site_inventory module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.site_inventory",
    entities=(
        Entity("StockLocation", label="data_paths.entity.stock_location"),
        Entity("StockItem", label="data_paths.entity.stock_item"),
        Entity("StockMovement", label="data_paths.entity.stock_movement"),
    ),
    inputs=(
        DataPath("oe_boq", "StockItem", via="StockItem.boq_position_id", label="data_paths.entity.position"),
        DataPath(
            "oe_procurement",
            "StockItem",
            via="StockItem.procurement_req_item_id",
            label="data_paths.entity.material_requisition_item",
        ),
    ),
)
