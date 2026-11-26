# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bimlv module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (read and write DIN SPEC 91350 BIM-LV containers: bundle a GAEB LV with its IFC/BIM model reference and the position-to-element link table, and materialize the links onto existing BOQ positions and BIM elements); reads code of bim_hub, boq",
)
