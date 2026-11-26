# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cost_plan module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (rolls a bill of quantities up into an NRM 1 elemental cost plan: group elements 0-8 with their elements, the building works estimate, the bill's markup cascade below it, cost per m2 of GIFA and share of total on every line, unallocated positions listed rather than dropped, and an Excel export with the same structure. Read-only); reads code of boq",
)
