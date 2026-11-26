# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bid_no_bid module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.bid_no_bid",
    entities=(
        Entity("BidNoBidScorecard", label="data_paths.entity.bid_no_bid_scorecard"),
        Entity("BidNoBidEvent", label="data_paths.entity.bid_no_bid_event"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of crm, tendering, win_loss",
)
