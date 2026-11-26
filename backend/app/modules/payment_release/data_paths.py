# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the payment_release module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.payment_release",
    entities=(
        Entity("InvoiceRelease", label="data_paths.entity.invoice_release"),
        Entity("PaymentTerms", label="data_paths.entity.payment_terms"),
        Entity("RetentionPosting", label="data_paths.entity.retention_posting"),
    ),
    inputs=(
        DataPath("oe_contracts", "PaymentTerms", via="PaymentTerms.contract_id", label="data_paths.entity.contract"),
    ),
)
