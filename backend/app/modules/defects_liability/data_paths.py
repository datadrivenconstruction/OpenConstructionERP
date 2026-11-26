# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the defects_liability module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.defects_liability",
    entities=(
        Entity("DlpWarranty", label="data_paths.entity.dlp_warranty"),
        Entity("DlpDefect", label="data_paths.entity.dlp_defect"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of documents, interface_management, payment_clock, temporary_works",
)
