# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the contacts module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.contacts",
    entities=(
        Entity("Contact", label="data_paths.entity.contact"),
        Entity("PartyLinkReview", label="data_paths.entity.party_link_review"),
    ),
    outputs=(
        DataPath("oe_accommodation", "Booking", via="Booking.occupant_contact_id", label="data_paths.entity.booking"),
        DataPath("oe_portal", "PortalUser", via="PortalUser.contact_id", label="data_paths.entity.portal_user"),
        DataPath("oe_property_dev", "Buyer", via="Buyer.contact_id", label="data_paths.entity.buyer"),
        DataPath("oe_tendering", "TenderBid", via="TenderBid.contact_id", label="data_paths.entity.tender_bid"),
    ),
)
