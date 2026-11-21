# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the tax_withholding module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.tax_withholding",
    roles=(
        "accountant",
        "project_manager",
        "authority",
    ),
    duties=(
        Duty("accountant", "data_paths.duty.tax_withholding.accountant"),
        Duty("project_manager", "data_paths.duty.tax_withholding.project_manager"),
        Duty("authority", "data_paths.duty.tax_withholding.authority"),
    ),
    entities=(
        Entity("WithholdingDeduction", label="data_paths.entity.withholding_deduction", route="/tax-withholding"),
        Entity("StatutoryTaxCalc", label="data_paths.entity.statutory_tax_calc", route="/tax-withholding"),
    ),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="WithholdingDeduction.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
    ),
)
