# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the norm_pricing module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (norm-based estimating settings per project: estimate wage, monthly hours, funding class and labour location, the graded hourly labour rates derived from them with the derivation shown, the norm-code and funding-cap checks of the norm_base and public_funding rule sets, labour rates written back to bill resources after a preview, and the bill in the market's estimate sheet columns. Shown only where a country pack supplies a norm base or pricing rules); reads code of boq",
)
