# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the pipelines module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.pipelines",
    entities=(
        Entity("Pipeline", label="data_paths.entity.pipeline"),
        Entity("PipelineRun", label="data_paths.entity.pipeline_run"),
        Entity("PipelineNodeState", label="data_paths.entity.pipeline_node_state"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, costs, validation",
)
