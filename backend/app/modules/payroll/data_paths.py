# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the payroll module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.payroll",
    entities=(
        Entity("PayrollBatch", label="data_paths.entity.payroll_batch"),
        Entity("PayrollPeriod", label="data_paths.entity.payroll_period"),
        Entity("PayrollDeduction", label="data_paths.entity.payroll_deduction"),
        Entity("PayrollEntry", label="data_paths.entity.payroll_entry"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of certified_payroll, costmodel, field_diary, field_time, fieldreports, finance and 2 more",
)
