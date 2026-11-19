# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the tendering module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Stale, Sum

DATA_PATHS = DataPaths(
    why="data_paths.why.tendering",
    roles=(
        "buyer",
        "estimator",
        "bidder",
    ),
    entities=(
        Entity("TenderPackage", label="data_paths.entity.tender_package", route="/tendering"),
        Entity("TenderBid", label="data_paths.entity.tender_bid", route="/tendering", measure=Sum("total_amount")),
        Entity("TenderBidInvitation", label="data_paths.entity.bid_invitation", route="/tendering"),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "TenderPackage",
            via="TenderPackage.boq_id",
            label="data_paths.entity.boq",
            route="/boq",
            importance="critical",
            breaks="data_paths.breaks.no_tender_scope",
            missing="data_paths.missing.no_boq_for_tender",
        ),
        DataPath(
            "oe_contacts",
            "TenderBid",
            via="TenderBid.contact_id",
            label="data_paths.entity.contact",
            route="/contacts",
        ),
    ),
    outputs=(
        DataPath(
            "oe_contracts",
            "Contract",
            via="Contract.metadata_.tender_package_id",
            label="data_paths.entity.contract",
            route="/contracts",
            measure=Sum("total_value"),
            importance="critical",
            breaks="data_paths.breaks.no_contract_value",
            missing="data_paths.missing.no_contract_for_tender",
        ),
    ),
    parameters=(
        Param("TenderBid.status", drives=("oe_contracts.Contract.total_value",), label="data_paths.param.award"),
    ),
    stale=(
        Stale(
            source="oe_boq.Position.updated_at",
            copy="TenderPackage.metadata_.last_distributed_at",
            label="data_paths.stale.changed_after_export",
        ),
    ),
)
