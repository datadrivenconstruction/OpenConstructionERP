# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the temporary_works module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.temporary_works",
    roles=(
        "engineer",
        "site_manager",
        "inspector",
    ),
    duties=(
        Duty("engineer", "data_paths.duty.temporary_works.engineer"),
        Duty("site_manager", "data_paths.duty.temporary_works.site_manager"),
        Duty("inspector", "data_paths.duty.temporary_works.inspector"),
    ),
    entities=(
        Entity("TemporaryWorksItem", label="data_paths.entity.temporary_works_item", route="/temporary-works"),
        Entity("TemporaryWorksPermit", label="data_paths.entity.temporary_works_permit", route="/temporary-works"),
    ),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="TemporaryWorksItem.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
        DataPath(
            "oe_schedule",
            "Activity",
            via="TemporaryWorksItem.schedule_activity_id",
            label="data_paths.entity.activity",
            route="/schedule",
            importance="high",
            breaks="data_paths.breaks.no_programme_link",
        ),
        DataPath(
            "oe_documents",
            "Document",
            via="TemporaryWorksItem.design_document_id",
            label="data_paths.entity.design_document",
            route="/documents",
            importance="high",
            breaks="data_paths.breaks.no_design_on_file",
        ),
        DataPath(
            "oe_formwork",
            "FormworkAssignment",
            via="TemporaryWorksItem.formwork_assignment_id",
            label="data_paths.entity.formwork_assignment",
            route="/formwork",
        ),
        DataPath(
            "oe_inspections",
            "QualityInspection",
            via="TemporaryWorksPermit.inspection_id",
            label="data_paths.entity.inspection",
            route="/inspections",
            importance="high",
            breaks="data_paths.breaks.no_use_inspection",
        ),
    ),
)
