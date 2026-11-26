# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the einvoice_zatca module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.einvoice_zatca",
    entities=(
        Entity("ZatcaEgsUnit", label="data_paths.entity.zatca_egs_unit"),
        Entity("ZatcaChainEntry", label="data_paths.entity.zatca_chain_entry"),
    ),
    inputs=(
        DataPath(
            "oe_einvoice_clearance",
            "ZatcaEgsUnit",
            via="ZatcaEgsUnit.profile_id",
            label="data_paths.entity.e_invoice_profile",
        ),
    ),
)
