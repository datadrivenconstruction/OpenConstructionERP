# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the client_errors module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (receives anonymised JS error reports from the frontend errorLogger and forwards them to the standard logging pipeline at WARNING level. Per-IP rate limited at 30/min. No DB storage in v4.2.x)",
)
