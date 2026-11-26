# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the variations module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.variations",
    entities=(
        Entity("DayworkSheet", label="data_paths.entity.daywork_sheet"),
        Entity("DisruptionClaim", label="data_paths.entity.disruption_claim"),
        Entity("ExtensionOfTimeClaim", label="data_paths.entity.extension_of_time_claim"),
        Entity("FinalAccount", label="data_paths.entity.final_account"),
    ),
    outputs=(
        DataPath(
            "oe_field_time",
            "FieldTimesheetLine",
            via="FieldTimesheetLine.variation_id",
            label="data_paths.entity.field_timesheet_line",
        ),
    ),
)
