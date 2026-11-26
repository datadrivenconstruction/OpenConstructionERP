# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the rate_feedback module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.rate_feedback",
    entities=(Entity("RateFeedbackProposal", label="data_paths.entity.rate_feedback_proposal"),),
    inputs=(
        DataPath(
            "oe_costs",
            "RateFeedbackProposal",
            via="RateFeedbackProposal.cost_item_id",
            label="data_paths.entity.cost_item",
        ),
    ),
)
