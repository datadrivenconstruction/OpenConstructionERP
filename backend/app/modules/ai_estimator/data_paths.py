# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the ai_estimator module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.ai_estimator",
    entities=(
        Entity("AiEstimatorRun", label="data_paths.entity.ai_estimator_run"),
        Entity("AiEstimatorGroup", label="data_paths.entity.ai_estimator_group"),
        Entity("AiEstimatorIntake", label="data_paths.entity.ai_estimator_intake"),
        Entity("AiEstimatorStep", label="data_paths.entity.ai_estimator_step"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of ai, ai_agents, bim_hub, boq, costs, documents and 3 more",
)
