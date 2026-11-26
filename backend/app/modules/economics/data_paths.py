# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the economics module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.economics",
    entities=(
        Entity("Approval", label="data_paths.entity.approval"),
        Entity("EconomicsPlan", label="data_paths.entity.economics_plan"),
        Entity("FlowLine", label="data_paths.entity.flow_line"),
        Entity("FrameLine", label="data_paths.entity.frame_line"),
    ),
    inputs=(
        DataPath(
            "oe_project_governance",
            "Approval",
            via="Approval.governance_document_id",
            label="data_paths.entity.governance_document",
        ),
    ),
)
