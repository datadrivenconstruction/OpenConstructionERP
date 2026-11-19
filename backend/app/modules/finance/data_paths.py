# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the finance module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum

DATA_PATHS = DataPaths(
    why="data_paths.why.finance",
    roles=(
        "accountant",
        "client",
        "supplier",
    ),
    entities=(
        Entity("Invoice", label="data_paths.entity.invoice", route="/finance", measure=Sum("amount_total")),
        Entity("Payment", label="data_paths.entity.payment", route="/finance", measure=Sum("amount")),
        Entity("ProjectBudget", label="data_paths.entity.budget", route="/finance"),
    ),
    inputs=(
        DataPath(
            "oe_contracts",
            "Invoice",
            via="Invoice.source_claim_id",
            label="data_paths.entity.progress_claim",
            route="/contracts",
            measure=Sum("amount_total"),
            importance="critical",
            breaks="data_paths.breaks.no_invoices",
            missing="data_paths.missing.no_claim_in_finance",
        ),
        DataPath(
            "oe_procurement",
            "Invoice",
            via="Invoice.purchase_order_id",
            label="data_paths.entity.purchase_order",
            route="/procurement",
            importance="high",
            breaks="data_paths.breaks.no_invoice_match",
        ),
        DataPath(
            "oe_contacts",
            "Invoice",
            via="Invoice.contact_id",
            label="data_paths.entity.contact",
            route="/contacts",
        ),
    ),
    outputs=(
        DataPath(
            "oe_costmodel",
            "InvoiceLineItem",
            via="InvoiceLineItem.cost_line_id",
            label="data_paths.entity.cost_line",
            route="/cost-model",
            importance="high",
            breaks="data_paths.breaks.no_actuals",
        ),
    ),
    parameters=(
        Param("Invoice.retention_amount", drives=("oe_costmodel:cash_flow",), label="data_paths.param.retention"),
        Param(
            "Invoice.due_date",
            drives=(
                "oe_costmodel:cash_flow",
                "oe_payment_clock:due_date",
            ),
            label="data_paths.param.due_date",
        ),
    ),
)
