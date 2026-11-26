# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the site_sensors module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.site_sensors",
    entities=(
        Entity("ConcreteMix", label="data_paths.entity.concrete_mix"),
        Entity("FormworkStrip", label="data_paths.entity.formwork_strip"),
        Entity("SensorAlert", label="data_paths.entity.sensor_alert"),
        Entity("SensorDevice", label="data_paths.entity.sensor_device"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of documents, integrations, notifications, schedule",
)
