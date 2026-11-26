# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the field_time module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.field_time",
    entities=(
        Entity("FieldClockConsent", label="data_paths.entity.field_clock_consent"),
        Entity("FieldClockSettings", label="data_paths.entity.field_clock_settings"),
        Entity("FieldSiteGeofence", label="data_paths.entity.field_site_geofence"),
        Entity("FieldTimesheet", label="data_paths.entity.field_timesheet"),
    ),
    inputs=(
        DataPath(
            "oe_variations",
            "FieldTimesheetLine",
            via="FieldTimesheetLine.variation_id",
            label="data_paths.entity.variation_order",
        ),
        DataPath(
            "oe_resources",
            "FieldTimesheetLine",
            via="FieldTimesheetLine.resource_id",
            label="data_paths.entity.resource",
        ),
        DataPath(
            "oe_equipment",
            "FieldTimesheetLine",
            via="FieldTimesheetLine.equipment_id",
            label="data_paths.entity.equipment",
        ),
    ),
)
