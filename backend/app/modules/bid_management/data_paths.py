# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bid_management module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.bid_management",
    entities=(
        Entity("BidPackage", label="data_paths.entity.bid_package"),
        Entity("TenderLegacyMap", label="data_paths.entity.tender_legacy_map"),
        Entity("BidAward", label="data_paths.entity.bid_award"),
        Entity("BidComparison", label="data_paths.entity.bid_comparison"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to tendering.package.awarded; publishes bid_management.award.deleted, bid_management.bidder.disqualified, bid_management.bidder.rejected, bid_management.bids.opened, bid_management.invitation.sent, bid_management.invitations.dispatched and 5 more; reads code of boq, contacts, contracts, costmodel, procurement, rfq_bidding and 2 more",
)
