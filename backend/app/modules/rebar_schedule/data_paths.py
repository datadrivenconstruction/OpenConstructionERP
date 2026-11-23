# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the rebar_schedule module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, External, Sum, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.rebar_schedule",
    roles=(
        "engineer",
        "estimator",
        "site_manager",
    ),
    duties=(
        Duty("engineer", "data_paths.duty.rebar_schedule.engineer"),
        Duty("estimator", "data_paths.duty.rebar_schedule.estimator"),
        Duty("site_manager", "data_paths.duty.rebar_schedule.site_manager"),
    ),
    external=(External("file", "data_paths.external.schedule_files"),),
    entities=(
        Entity(
            "RebarScheduleImport",
            label="data_paths.entity.rebar_import",
            route="/rebar-schedule",
            measure=Sum("total_weight_kg"),
        ),
        Entity(
            "BarBendingEntry",
            label="data_paths.entity.bar_bending_entry",
            route="/rebar-schedule",
            measure=Sum("weight_kg"),
        ),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "BarBendingEntry",
            via="BarBendingEntry.boq_position_id",
            measure=Sum("weight_kg"),
            label="data_paths.entity.position",
            route="/boq",
            importance="high",
            breaks="data_paths.breaks.no_steel_check",
        ),
    ),
    outputs=(
        DataPath(
            "oe_cutting",
            "CuttingJob",
            via="CuttingJob.source_ref",
            label="data_paths.entity.cutting_job",
            route="/cutting",
            where=(Where("source_type", "eq", "rebar_schedule"),),
        ),
    ),
)
