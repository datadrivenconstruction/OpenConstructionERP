# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the us_ca_pack module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (california construction rules on top of the US pack: the district sales tax stack and the split between materials the contractor consumes and fixtures it sells, the state prevailing wage regime and its thresholds, the public and private retention caps, and the statutory payment and lien clocks); reads code of contracts, us_pack",
)
