# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the timeline module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (unified, cross-module project timeline over the existing activity-log store (no new table) - a newest-first, filterable feed of significant domain events rolled up to their umbrella project, the history of any single record, and an event-bus bridge subscriber that persists those events so the timeline survives a restart)",
)
