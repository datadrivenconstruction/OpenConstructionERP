# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the authority_submission module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity, External

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
)
