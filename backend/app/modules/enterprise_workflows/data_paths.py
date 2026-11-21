# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the enterprise_workflows module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.enterprise_workflows",
    roles=(
        "project_manager",
        "accountant",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.enterprise_workflows.project_manager"),
        Duty("accountant", "data_paths.duty.enterprise_workflows.accountant"),
    ),
    entities=(
        Entity("ApprovalWorkflow", label="data_paths.entity.approval_workflow", route="/workflows"),
        Entity("ApprovalRequest", label="data_paths.entity.approval_request", route="/workflows"),
    ),
)
