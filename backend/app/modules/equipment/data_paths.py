# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the equipment module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.equipment",
    entities=(
        Entity("EquipmentRental", label="data_paths.entity.equipment_rental"),
        Entity("UtilisationDay", label="data_paths.entity.utilisation_day"),
        Entity("EquipmentRateCatalogue", label="data_paths.entity.equipment_rate_catalogue"),
        Entity("EquipmentRateProfile", label="data_paths.entity.equipment_rate_profile"),
    ),
    outputs=(
        DataPath(
            "oe_field_time",
            "FieldTimesheetLine",
            via="FieldTimesheetLine.equipment_id",
            label="data_paths.entity.field_timesheet_line",
        ),
    ),
)
