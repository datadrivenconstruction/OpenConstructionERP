# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the china_pack module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.china_pack",
    entities=(Entity("ChinaFeeProfile", label="data_paths.entity.china_fee_profile"),),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, einvoice_clearance, finance, project_tax, tax_withholding",
)
