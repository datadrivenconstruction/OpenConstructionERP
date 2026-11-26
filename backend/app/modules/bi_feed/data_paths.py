# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bi_feed module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (read-only flat tables (CSV, Parquet, JSON) over projects, BOQ positions, invoices, purchase orders and schedule activities, for Excel, Power Query and any BI tool; optional PostgreSQL views for SQL access); reads code of boq, finance, procurement, schedule",
)
