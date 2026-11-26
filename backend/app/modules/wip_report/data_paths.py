# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the wip_report module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.wip_report",
    entities=(
        Entity("WipForecast", label="data_paths.entity.wip_forecast"),
        Entity("WipPeriod", label="data_paths.entity.wip_period"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to cvr.report.finalized; reads code of changeorders, contracts, cvr, finance",
)
