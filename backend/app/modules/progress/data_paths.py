# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the progress module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.progress",
    entities=(
        Entity("ProgressEntry", label="data_paths.entity.progress_entry"),
        Entity("ProgressPlan", label="data_paths.entity.progress_plan"),
    ),
    inputs=(
        DataPath("oe_boq", "ProgressEntry", via="ProgressEntry.boq_position_id", label="data_paths.entity.position"),
    ),
)
