# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the project_controls module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (executive cross-module controls dashboard. Cost (EVM), schedule, quality, safety, risk and change KPIs side by side, currency-honest, with one-click drill-down to the owning module. Pure read-only consumer over the shared KPI registry); reads code of bi_dashboards",
)
