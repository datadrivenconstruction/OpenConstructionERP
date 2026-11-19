# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the changeorders module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.changeorders",
    roles=(
        "contractor",
        "client",
        "quantity_surveyor",
        "engineer",
    ),
    entities=(
        Entity(
            "ChangeOrder", label="data_paths.entity.change_order", route="/changeorders", measure=Sum("approved_amount")
        ),
        Entity("ChangeOrderItem", label="data_paths.entity.change_order_item", route="/changeorders"),
    ),
    inputs=(
        DataPath(
            "oe_ncr",
            "NCR",
            via="NCR.change_order_id",
            label="data_paths.entity.ncr",
            route="/ncr",
        ),
        DataPath(
            "oe_procurement",
            "ChangeOrder",
            via="ChangeOrder.linked_po_ids",
            label="data_paths.entity.purchase_order",
            route="/procurement",
        ),
        DataPath(
            "oe_rfi",
            "ChangeOrder",
            via="ChangeOrder.linked_rfi_ids",
            label="data_paths.entity.rfi",
            route="/rfi",
        ),
    ),
    outputs=(
        DataPath(
            "oe_contracts",
            "SovAdjustment",
            via="SovAdjustment.source_id",
            label="data_paths.entity.sov_adjustment",
            route="/contracts",
            measure=Sum("delta_value"),
            where=(Where("source_kind", "eq", "change_order"),),
            importance="high",
            breaks="data_paths.breaks.no_contract_value",
        ),
    ),
    parameters=(
        Param(
            "ChangeOrder.approved_amount",
            drives=(
                "oe_contracts.Contract.total_value",
                "oe_costmodel:budget",
            ),
            label="data_paths.param.approved_amount",
        ),
        Param("ChangeOrder.approved_time_days", drives=("oe_schedule:end_date",), label="data_paths.param.time_impact"),
    ),
)
