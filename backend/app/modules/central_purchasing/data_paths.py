# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the central purchasing module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Sum

DATA_PATHS = DataPaths(
    why="data_paths.why.procurement",
    roles=("buyer", "contractor"),
    entities=(
        Entity("Bundle", label="data_paths.entity.tender_package", route="/central-purchasing", scope="global"),
        Entity("AwardSplit", label="data_paths.entity.contract", route="/central-purchasing", measure=Sum("net")),
    ),
    inputs=(),
    outputs=(
        DataPath(
            "oe_contracts",
            "Contract",
            via="AwardSplit.document_id",
            label="data_paths.entity.contract",
            route="/contracts",
            measure=Sum("total_value"),
            importance="high",
            breaks="data_paths.breaks.no_contract_value",
        ),
        DataPath(
            "oe_procurement",
            "PurchaseOrder",
            via="AwardSplit.document_id",
            label="data_paths.entity.purchase_order",
            route="/procurement",
            importance="high",
            breaks="data_paths.breaks.no_commitments",
        ),
    ),
)
