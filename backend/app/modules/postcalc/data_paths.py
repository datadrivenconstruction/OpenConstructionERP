# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the postcalc module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (reconciles the estimate against site actuals into planned-vs-actual labour productivity and material cost: a factor per BoQ line and per resource category, the material really consumed against what the estimate allowed, a project rollup, a ranked list of productivity factors to feed back into estimating, and the same comparison rolled up per production norm so a norm library can be corrected from what the jobs priced with it actually cost. Reads existing BoQ positions, field timesheets, progress readings and the site material ledger; a stateless analysis layer that adds no table); reads code of boq, costmodel, equipment, field_time, norm_expansion, price_breakdown and 3 more",
)
