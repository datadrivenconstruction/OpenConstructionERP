# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the staffing module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.staffing",
    entities=(
        Entity("PersonnelFile", label="data_paths.entity.personnel_file"),
        Entity("StaffingPlan", label="data_paths.entity.staffing_plan"),
        Entity("HandoverLink", label="data_paths.entity.handover_link"),
        Entity("LeaveRecord", label="data_paths.entity.leave_record"),
    ),
    inputs=(
        DataPath(
            "oe_project_governance",
            "StaffingPlan",
            via="StaffingPlan.governance_document_id",
            label="data_paths.entity.governance_document",
        ),
    ),
)
