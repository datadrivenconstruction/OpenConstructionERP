# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bid_day module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.bid_day",
    entities=(
        Entity("BidDayBoard", label="data_paths.entity.bid_day_board"),
        Entity("BidDaySnapshot", label="data_paths.entity.bid_day_snapshot"),
        Entity("BidDayEvent", label="data_paths.entity.bid_day_event"),
        Entity("BidDayQuote", label="data_paths.entity.bid_day_quote"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of bid_management, boq, fx, tendering",
)
