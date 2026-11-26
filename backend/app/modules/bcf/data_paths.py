# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bcf module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.bcf",
    entities=(
        Entity("BCFTopic", label="data_paths.entity.bcf_topic"),
        Entity("BCFComment", label="data_paths.entity.bcf_comment"),
        Entity("BCFViewpoint", label="data_paths.entity.bcf_viewpoint"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of bim_hub, clash",
)
