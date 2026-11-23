# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the authority_submission module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, External

DATA_PATHS = DataPaths(
    why="data_paths.why.authority_submission",
    roles=(
        "project_manager",
        "engineer",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.authority_submission.project_manager"),
        Duty("engineer", "data_paths.duty.authority_submission.engineer"),
    ),
    external=(External("party", "data_paths.external.authority"),),
    entities=(
        Entity("Submission", label="data_paths.entity.submission", route="/authority-submissions"),
        Entity("SubmissionProfile", label="data_paths.entity.submission_profile", route="/authority-submissions"),
    ),
    outputs=(
        DataPath(
            "oe_permits",
            "PermitApplication",
            via="PermitApplication.submission_id",
            label="data_paths.entity.permit_application",
            route="/permits",
            importance="high",
            breaks="data_paths.breaks.permit_without_submission",
        ),
        DataPath(
            "oe_design_management",
            "DesignPermit",
            via="DesignPermit.authority_submission_id",
            label="data_paths.entity.design_permit",
        ),
    ),
)
