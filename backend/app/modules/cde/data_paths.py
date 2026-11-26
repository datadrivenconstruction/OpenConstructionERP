# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cde module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.cde",
    entities=(
        Entity("CdeSettings", label="data_paths.entity.cde_settings"),
        Entity("DocumentContainer", label="data_paths.entity.document_container"),
        Entity("DocumentRevision", label="data_paths.entity.document_revision"),
        Entity("StateTransition", label="data_paths.entity.state_transition"),
    ),
    outputs=(
        DataPath(
            "oe_design_management",
            "DesignDrawing",
            via="DesignDrawing.container_id",
            label="data_paths.entity.design_drawing",
        ),
    ),
)
