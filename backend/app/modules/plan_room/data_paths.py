# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the plan_room module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.plan_room",
    entities=(Entity("PlanPin", label="data_paths.entity.plan_pin"),),
    reason="No foreign key joins its tables to another module's tables; reads code of documents, markups, punchlist, takeoff",
)
