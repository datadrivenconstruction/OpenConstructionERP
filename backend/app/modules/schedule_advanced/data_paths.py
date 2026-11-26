# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the schedule_advanced module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.schedule_advanced",
    entities=(
        Entity("Calendar", label="data_paths.entity.calendar"),
        Entity("DelayAnalysis", label="data_paths.entity.delay_analysis"),
        Entity("MasterSchedule", label="data_paths.entity.master_schedule"),
        Entity("WeeklyCommitment", label="data_paths.entity.weekly_commitment"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes schedule_advanced.baseline.captured, schedule_advanced.commitment.completed, schedule_advanced.commitment.made, schedule_advanced.commitment.missed, schedule_advanced.constraint.cleared, schedule_advanced.phase.pulled and 4 more; reads code of boq, construction_control, notifications, procurement, resources, rfi and 4 more",
)
