# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the permits module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.permits",
    entities=(
        Entity("PermitRequirement", label="data_paths.entity.permit_requirement"),
        Entity("PermitRoadmap", label="data_paths.entity.permit_roadmap"),
        Entity("ClockEvent", label="data_paths.entity.clock_event"),
        Entity("ConditionDischarge", label="data_paths.entity.condition_discharge"),
    ),
    inputs=(
        DataPath(
            "oe_project_governance",
            "PermitRoadmap",
            via="PermitRoadmap.governance_document_id",
            label="data_paths.entity.governance_document",
        ),
    ),
)
