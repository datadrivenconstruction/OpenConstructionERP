# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the engineering_brief module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.engineering_brief",
    entities=(
        Entity("EngineeringBrief", label="data_paths.entity.engineering_brief"),
        Entity("ConceptItem", label="data_paths.entity.concept_item"),
        Entity("FrameMilestone", label="data_paths.entity.frame_milestone"),
        Entity("ProgrammeLine", label="data_paths.entity.programme_line"),
    ),
    inputs=(
        DataPath(
            "oe_requirements",
            "EngineeringBrief",
            via="EngineeringBrief.requirement_set_id",
            label="data_paths.entity.requirement_set",
        ),
        DataPath(
            "oe_project_governance",
            "EngineeringBrief",
            via="EngineeringBrief.governance_document_id",
            label="data_paths.entity.governance_document",
        ),
        DataPath(
            "oe_schedule", "EngineeringBrief", via="EngineeringBrief.schedule_id", label="data_paths.entity.schedule"
        ),
    ),
)
