# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the condition module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.condition",
    entities=(
        Entity("ConditionAssessment", label="data_paths.entity.condition_assessment"),
        Entity("ConditionScale", label="data_paths.entity.condition_scale"),
        Entity("ConditionAction", label="data_paths.entity.condition_action"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of bim_hub, carbon, price_index",
)
