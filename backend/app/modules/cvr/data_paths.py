# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cvr module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.cvr",
    entities=(
        Entity("CashflowPoint", label="data_paths.entity.cashflow_point"),
        Entity("CvrReport", label="data_paths.entity.cvr_report"),
        Entity("PaymentApplication", label="data_paths.entity.payment_application"),
        Entity("CvrLine", label="data_paths.entity.cvr_line"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes cvr.report.created, cvr.report.finalized; reads code of boq, contracts, costmodel, field_time, finance, subcontractors",
)
