# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the change_intelligence module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (analytical layer over the change-management family (change orders, variation notices / requests / orders, management-of-change entries). Reads their live state to answer what is waiting on whom and for how long (cycle-time telemetry), with no tables of its own and no migration - it queries the existing change records); reads code of approval_routes, boq, changeorders, claims_evidence, contracts, correspondence and 8 more",
)
