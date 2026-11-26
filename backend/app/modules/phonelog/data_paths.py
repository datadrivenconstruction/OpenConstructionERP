# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the phonelog module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.phonelog",
    entities=(Entity("PhoneLog", label="data_paths.entity.phone_log"),),
    reason="No foreign key joins its tables to another module's tables; publishes phone_log.created, phone_log.recording_ingested; reads code of ai",
)
