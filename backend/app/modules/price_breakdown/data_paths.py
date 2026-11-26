# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the price_breakdown module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (unit-price analysis library: splits a position rate into labour, material, plant, subcontract and other, plus overhead, risk and profit markup); reads code of boq, resource_summary",
)
