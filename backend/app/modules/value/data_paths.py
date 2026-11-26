# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the value module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.value",
    entities=(Entity("TimeSavedFactor", label="data_paths.entity.time_saved_factor"),),
    reason="No foreign key joins its tables to another module's tables; reads code of ai_agents, approval_routes, boq, change_intelligence, changeorders, cost_recovery and 2 more",
)
