# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the einvoice_clearance module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.einvoice_clearance",
    entities=(
        Entity("EInvoiceDocument", label="data_paths.entity.e_invoice_document"),
        Entity("EInvoiceProfile", label="data_paths.entity.e_invoice_profile"),
        Entity("EInvoiceEvent", label="data_paths.entity.e_invoice_event"),
    ),
    outputs=(
        DataPath(
            "oe_einvoice_zatca", "ZatcaEgsUnit", via="ZatcaEgsUnit.profile_id", label="data_paths.entity.zatca_egs_unit"
        ),
    ),
)
