# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the us_tx_pack module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (texas construction rules on top of the US pack: how a lump sum contract and a separated contract split the sales tax on materials, the locally determined prevailing wage, the public works retainage caps and their contract-value threshold, and the statutory payment and lien clocks); reads code of us_pack",
)
