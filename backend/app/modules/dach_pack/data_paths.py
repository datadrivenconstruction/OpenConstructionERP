# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the dach_pack module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (dACH construction standards: GAEB XML exchange formats, VOB/B contract terms, DIN 276 cost groups, HOAI fee schedules, MwSt, and Abschlagsrechnung templates); reads code of finance, subcontractors",
)
