# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the deadlines module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (cross-module overdue escalation - a unified deadline register plus a background sweep that notifies owners, escalates to managers past a grace window, and rolls repeat overdue items into the notification digest); reads code of bid_management, compliance_docs, contracts, correspondence, dashboard, defects_liability and 11 more",
)
