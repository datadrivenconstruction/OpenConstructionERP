# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the compliance module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.compliance",
    roles=(
        "project_manager",
        "engineer",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.compliance.project_manager"),
        Duty("engineer", "data_paths.duty.compliance.engineer"),
    ),
    entities=(Entity("ComplianceDSLRule", label="data_paths.entity.compliance_rule", route="/compliance/builder"),),
)
