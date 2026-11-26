# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the match_elements module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.match_elements",
    entities=(
        Entity("MatchSession", label="data_paths.entity.match_session"),
        Entity("MatchSearchLog", label="data_paths.entity.match_search_log"),
        Entity("MatchPromptTemplate", label="data_paths.entity.match_prompt_template"),
        Entity("MatchTemplate", label="data_paths.entity.match_template"),
    ),
    inputs=(
        DataPath(
            "oe_costs", "MatchTemplate", via="MatchTemplate.cwicr_position_id", label="data_paths.entity.cost_item"
        ),
    ),
)
