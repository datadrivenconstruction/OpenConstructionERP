# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the procurement_concept module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.procurement_concept",
    entities=(
        Entity("AwardPackage", label="data_paths.entity.award_package"),
        Entity("BidderCandidate", label="data_paths.entity.bidder_candidate"),
        Entity("MarketSounding", label="data_paths.entity.market_sounding"),
        Entity("PrequalProfile", label="data_paths.entity.prequal_profile"),
    ),
    inputs=(
        DataPath(
            "oe_project_governance",
            "ProcurementConcept",
            via="ProcurementConcept.governance_document_id",
            label="data_paths.entity.governance_document",
        ),
    ),
)
