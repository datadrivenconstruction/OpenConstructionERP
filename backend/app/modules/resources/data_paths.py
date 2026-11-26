# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the resources module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.resources",
    entities=(
        Entity("Assignment", label="data_paths.entity.assignment"),
        Entity("ResourceRequest", label="data_paths.entity.resource_request"),
        Entity("Resource", label="data_paths.entity.resource"),
        Entity("Skill", label="data_paths.entity.skill"),
    ),
    outputs=(
        DataPath(
            "oe_field_time",
            "FieldTimesheetLine",
            via="FieldTimesheetLine.resource_id",
            label="data_paths.entity.field_timesheet_line",
        ),
    ),
)
