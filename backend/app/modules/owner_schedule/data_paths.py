# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the owner_schedule module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.owner_schedule",
    entities=(
        Entity("OwnerSchedule", label="data_paths.entity.owner_schedule"),
        Entity("OwnerScheduleProfile", label="data_paths.entity.owner_schedule_profile"),
        Entity("OwnerScheduleItem", label="data_paths.entity.owner_schedule_item"),
    ),
    inputs=(DataPath("oe_boq", "OwnerSchedule", via="OwnerSchedule.boq_id", label="data_paths.entity.boq"),),
)
