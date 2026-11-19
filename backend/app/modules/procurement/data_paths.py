# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the procurement module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum

DATA_PATHS = DataPaths(
    why="data_paths.why.procurement",
    roles=(
        "buyer",
        "supplier",
    ),
    entities=(
        Entity("MaterialRequisition", label="data_paths.entity.requisition", route="/procurement"),
        Entity(
            "PurchaseOrder", label="data_paths.entity.purchase_order", route="/procurement", measure=Sum("amount_total")
        ),
        Entity("GoodsReceipt", label="data_paths.entity.goods_receipt", route="/procurement"),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "MaterialRequisitionItemSource",
            via="MaterialRequisitionItemSource.boq_position_id",
            label="data_paths.entity.position",
            route="/boq",
            importance="high",
            breaks="data_paths.breaks.no_quantities",
        ),
        DataPath(
            "oe_contacts",
            "PurchaseOrder",
            via="PurchaseOrder.vendor_contact_id",
            label="data_paths.entity.vendor",
            route="/contacts",
        ),
        DataPath(
            "oe_schedule",
            "MaterialRequisitionItem",
            via="MaterialRequisitionItem.schedule_activity_id",
            label="data_paths.entity.activity",
            route="/schedule",
        ),
    ),
    outputs=(
        DataPath(
            "oe_finance",
            "Invoice",
            via="Invoice.purchase_order_id",
            label="data_paths.entity.invoice",
            route="/finance",
            measure=Sum("amount_total"),
            importance="high",
            breaks="data_paths.breaks.no_invoice_match",
        ),
        DataPath(
            "oe_costmodel",
            "PurchaseOrderItem",
            via="PurchaseOrderItem.cost_line_id",
            label="data_paths.entity.cost_line",
            route="/cost-model",
        ),
    ),
    parameters=(
        Param(
            "PurchaseOrder.retention_percent",
            drives=(
                "PORetainageRelease.release_amount",
                "oe_finance.Invoice.retention_amount",
            ),
            label="data_paths.param.retention",
        ),
        Param(
            "PurchaseOrder.tax_rate_pct",
            drives=(
                "PurchaseOrder.amount_total",
                "oe_finance.Invoice.tax_amount",
            ),
            label="data_paths.param.tax_rate",
        ),
    ),
)
