# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the clash module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.clash",
    entities=(
        Entity("ClashProfile", label="data_paths.entity.clash_profile"),
        Entity("ClashRun", label="data_paths.entity.clash_run"),
        Entity("ClashSuppression", label="data_paths.entity.clash_suppression"),
        Entity("ClashIssue", label="data_paths.entity.clash_issue"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of bcf, bim_hub, clash_cost_impact, notifications, punchlist, schedule and 1 more",
)
