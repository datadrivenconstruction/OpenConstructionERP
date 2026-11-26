# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the record_publishing module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (publish a project record - a daily site diary today, meeting minutes and inspection reports next - as one signed PDF and distribute it to a named set of recipients who acknowledge receipt, all in a single action. A thin orchestrator over the record renderers, the storage backend and the file-transmittals engine, so it adds no tables); publishes record.published; reads code of daily_diary, file_distribution, file_transmittals, meetings",
)
