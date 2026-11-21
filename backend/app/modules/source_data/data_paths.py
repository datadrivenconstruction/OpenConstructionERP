# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the source_data module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, External

DATA_PATHS = DataPaths(
    why="data_paths.why.source_data",
    roles=(
        "project_manager",
        "surveyor",
        "engineer",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.source_data.project_manager"),
        Duty("surveyor", "data_paths.duty.source_data.surveyor"),
        Duty("engineer", "data_paths.duty.source_data.engineer"),
    ),
    external=(External("file", "data_paths.external.source_documents"),),
    entities=(
        Entity("SourceDocument", label="data_paths.entity.source_document", route="/source-data"),
        Entity("SourceChecklistItem", label="data_paths.entity.source_checklist_item", route="/source-data"),
    ),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="SourceDocument.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
    ),
)
