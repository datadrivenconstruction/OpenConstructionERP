# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_approvals module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_approvals",
    roles=(
        "project_manager",
        "engineer",
        "architect",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.file_approvals.project_manager"),
        Duty("engineer", "data_paths.duty.file_approvals.engineer"),
        Duty("architect", "data_paths.duty.file_approvals.architect"),
    ),
    entities=(
        Entity("FileApprovalWorkflow", label="data_paths.entity.file_approval", route="/files/approvals"),
        Entity("FileStampTemplate", label="data_paths.entity.stamp_template", route="/files/approvals"),
    ),
)
