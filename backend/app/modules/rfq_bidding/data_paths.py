# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the rfq_bidding module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.rfq_bidding",
    entities=(
        Entity("RFQ", label="data_paths.entity.rfq"),
        Entity("RFQAward", label="data_paths.entity.rfq_award"),
        Entity("RFQBid", label="data_paths.entity.rfq_bid"),
        Entity("RFQBidAdjustment", label="data_paths.entity.rfq_bid_adjustment"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of bid_management, boq, contacts, price_breakdown",
)
