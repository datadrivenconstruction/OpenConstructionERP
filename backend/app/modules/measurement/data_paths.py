# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the measurement module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (formula-based quantity take-off library: every quantity keeps the formula that produced it, with presets for REB 23.003, OENORM A 2063, NRM and CESMM); reads code of price_breakdown",
)
