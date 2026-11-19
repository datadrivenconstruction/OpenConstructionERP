# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the costmodel module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum

DATA_PATHS = DataPaths(
    why="data_paths.why.costmodel",
    roles=(
        "quantity_surveyor",
        "accountant",
        "project_manager",
    ),
    entities=(
        Entity("CostLine", label="data_paths.entity.cost_line", route="/cost-model"),
        Entity("BudgetLine", label="data_paths.entity.budget_line", route="/cost-model"),
        Entity("CashFlow", label="data_paths.entity.cash_flow", route="/cost-model"),
        Entity("CostSnapshot", label="data_paths.entity.cost_snapshot", route="/cost-model"),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "CostLine",
            via="CostLine.boq_position_id",
            label="data_paths.entity.position",
            route="/boq",
            importance="critical",
            breaks="data_paths.breaks.no_budget",
        ),
        DataPath(
            "oe_contracts",
            "Contract",
            via="Contract.cost_line_id",
            label="data_paths.entity.contract",
            route="/contracts",
            measure=Sum("total_value"),
            importance="high",
            breaks="data_paths.breaks.no_commitments",
        ),
        DataPath(
            "oe_procurement",
            "PurchaseOrderItem",
            via="PurchaseOrderItem.cost_line_id",
            label="data_paths.entity.po_line",
            route="/procurement",
            importance="high",
            breaks="data_paths.breaks.no_commitments",
        ),
        DataPath(
            "oe_finance",
            "InvoiceLineItem",
            via="InvoiceLineItem.cost_line_id",
            label="data_paths.entity.invoice_line",
            route="/finance",
            importance="high",
            breaks="data_paths.breaks.no_actuals",
        ),
        DataPath(
            "oe_schedule",
            "BudgetLine",
            via="BudgetLine.activity_id",
            label="data_paths.entity.activity",
            route="/schedule",
        ),
    ),
    parameters=(
        Param(
            "CostControlSettings.forecast_method",
            drives=("CostForecastSnapshot.totals",),
            label="data_paths.param.forecast_method",
        ),
    ),
)
