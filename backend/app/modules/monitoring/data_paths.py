# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the monitoring module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.monitoring",
    roles=("surveyor", "engineer", "site_manager"),
    duties=(
        Duty("surveyor", "data_paths.duty.monitoring.surveyor"),
        Duty("engineer", "data_paths.duty.monitoring.engineer"),
        Duty("site_manager", "data_paths.duty.monitoring.site_manager"),
    ),
    external=(External("device", "data_paths.external.sensors"),),
    chips=(Chip("MonitoringAlert", "data_paths.chip.alert_open", (Where("acknowledged_at", "is_null"),), "error"),),
    entities=(
        Entity("MonitoringPoint", label="data_paths.entity.monitoring_point", route="/survey/monitoring"),
        Entity("MonitoringReading", label="data_paths.entity.reading", route="/survey/monitoring"),
        Entity("MonitoringAlert", label="data_paths.entity.alert", route="/survey/monitoring"),
    ),
    outputs=(
        DataPath(
            "oe_risk",
            "MonitoringAlert",
            via="MonitoringAlert.risk_id",
            label="data_paths.entity.risk",
            route="/risks",
            importance="high",
            breaks="data_paths.breaks.alarm_unseen",
            where=(Where("risk_id", "not_null"),),
        ),
    ),
)
