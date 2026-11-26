# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the design_management module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.design_management",
    entities=(
        Entity("DesignApprovalPoint", label="data_paths.entity.design_approval_point"),
        Entity("DesignDeliverable", label="data_paths.entity.design_deliverable"),
        Entity("DesignDistributionRule", label="data_paths.entity.design_distribution_rule"),
        Entity("DesignDrawing", label="data_paths.entity.design_drawing"),
    ),
    inputs=(
        DataPath(
            "oe_cde", "DesignDrawing", via="DesignDrawing.container_id", label="data_paths.entity.document_container"
        ),
    ),
)
