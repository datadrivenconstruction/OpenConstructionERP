# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the certified_payroll module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.certified_payroll",
    entities=(
        Entity("CertifiedPayrollWeek", label="data_paths.entity.certified_payroll_week"),
        Entity("WageDetermination", label="data_paths.entity.wage_determination"),
        Entity("WorkerClassificationAssignment", label="data_paths.entity.worker_classification_assignment"),
        Entity("CertifiedPayrollLine", label="data_paths.entity.certified_payroll_line"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of payroll",
)
