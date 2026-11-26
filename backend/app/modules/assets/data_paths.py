# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the assets module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (operational-phase asset intelligence: discover asset candidates from BIM models, compute warranty / maintenance / lifecycle health, roll up a portfolio summary, and dispatch warranty-expiry alerts. Reads the BIM-sourced asset register; persists nothing of its own (state rides the existing asset_info JSON)); reads code of bim_hub, notifications",
)
