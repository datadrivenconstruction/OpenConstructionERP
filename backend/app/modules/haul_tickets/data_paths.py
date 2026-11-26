# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the haul_tickets module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.haul_tickets",
    entities=(
        Entity("HaulInvoice", label="data_paths.entity.haul_invoice"),
        Entity("HaulMaterial", label="data_paths.entity.haul_material"),
        Entity("HaulRate", label="data_paths.entity.haul_rate"),
        Entity("HaulSettings", label="data_paths.entity.haul_settings"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of site_logistics, stockpiles, surfaces_volumes",
)
