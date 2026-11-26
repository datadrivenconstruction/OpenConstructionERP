# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the estimate_archive module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.estimate_archive",
    entities=(
        Entity("EstimateSeal", label="data_paths.entity.estimate_seal"),
        Entity("EstimateSealAttachment", label="data_paths.entity.estimate_seal_attachment"),
        Entity("EstimateSealReceipt", label="data_paths.entity.estimate_seal_receipt"),
        Entity("SealDerivation", label="data_paths.entity.seal_derivation"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, changeorders, contracts, costs, documents, signing and 1 more",
)
