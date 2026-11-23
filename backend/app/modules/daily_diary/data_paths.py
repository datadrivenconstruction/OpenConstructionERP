# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the daily_diary module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.daily_diary",
    roles=("site_manager", "subcontractor", "client"),
    duties=(
        Duty("site_manager", "data_paths.duty.daily_diary.site_manager"),
        Duty("subcontractor", "data_paths.duty.daily_diary.subcontractor"),
        Duty("client", "data_paths.duty.daily_diary.client"),
    ),
    external=(External("device", "data_paths.external.weather_service"),),
    chips=(Chip("DailyDiary", "data_paths.chip.diary_open", (Where("status", "eq", "open"),), "info"),),
    entities=(
        Entity("DailyDiary", label="data_paths.entity.diary", route="/daily-diary"),
        Entity("DiaryEntry", label="data_paths.entity.diary_entry", route="/daily-diary"),
        Entity("DiaryPhoto", label="data_paths.entity.site_photo", route="/daily-diary"),
    ),
    inputs=(
        DataPath(
            "oe_schedule_advanced",
            "DiaryEntry",
            via="DiaryEntry.source_ref",
            label="data_paths.entity.lps_entry",
            route="/schedule",
            where=(Where("source_module", "eq", "schedule_advanced"),),
        ),
        DataPath(
            "oe_site_sensors",
            "SensorAlert",
            via="SensorAlert.diary_id",
            label="data_paths.entity.alert",
            route="/site-sensors",
        ),
    ),
)
