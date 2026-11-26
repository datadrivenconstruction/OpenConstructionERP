# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the ai module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.ai",
    entities=(
        Entity("AIEstimateJob", label="data_paths.entity.ai_estimate_job"),
        Entity("AISettings", label="data_paths.entity.ai_settings"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes ai.boq.created, ai.estimate.completed, ai.settings.updated; reads code of boq, costs",
)
