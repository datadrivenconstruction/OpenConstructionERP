# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cost_match module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.cost_match",
    entities=(
        Entity("MatchRun", label="data_paths.entity.match_run"),
        Entity("MatchResult", label="data_paths.entity.match_result"),
        Entity("MatchDecision", label="data_paths.entity.match_decision"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of costs, dashboards",
)
