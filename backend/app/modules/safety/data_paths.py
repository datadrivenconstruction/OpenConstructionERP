# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the safety module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, Sum, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.safety",
    roles=(
        "site_manager",
        "inspector",
        "contractor",
    ),
    duties=(
        Duty("site_manager", "data_paths.duty.safety.site_manager"),
        Duty("inspector", "data_paths.duty.safety.inspector"),
        Duty("contractor", "data_paths.duty.safety.contractor"),
    ),
    entities=(
        Entity("SafetyIncident", label="data_paths.entity.safety_incident", route="/safety", measure=Sum("days_lost")),
        Entity("SafetyObservation", label="data_paths.entity.safety_observation", route="/safety"),
    ),
    inputs=(
        DataPath(
            "oe_fieldreports",
            "FieldReport",
            via="SafetyObservation.metadata_.field_report_id",
            label="data_paths.entity.field_report",
            route="/field-reports",
        ),
        DataPath(
            "oe_site_sensors",
            "SensorAlert",
            via="SafetyObservation.metadata_.sensor_alert_id",
            label="data_paths.entity.alert",
            route="/site-sensors",
            breaks="data_paths.breaks.alarm_unseen",
        ),
    ),
    outputs=(
        DataPath(
            "oe_hse_advanced",
            "HSEIncidentInvestigation",
            via="HSEIncidentInvestigation.incident_ref",
            label="data_paths.entity.incident_investigation",
            route="/hse-advanced",
            importance="high",
            breaks="data_paths.breaks.incident_not_investigated",
        ),
        DataPath(
            "oe_hse_advanced",
            "CorrectiveAction",
            via="CorrectiveAction.source_ref",
            label="data_paths.entity.corrective_action",
            route="/hse-advanced",
            where=(Where("source_type", "eq", "incident"),),
        ),
    ),
)
