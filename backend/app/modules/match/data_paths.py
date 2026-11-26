# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the match module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (element-to-CWICR vector matcher. Takes a BIM/PDF/DWG/photo element and returns ranked CWICR cost-position candidates with classification, unit, region, and lex boosts); reads code of ai, bim_hub, boq",
)
