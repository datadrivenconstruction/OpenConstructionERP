# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the tax_withholding module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, Sum, Where

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
        Entity(
            "WithholdingDeduction",
            label="data_paths.entity.withholding_deduction",
            route="/tax-withholding",
            measure=Sum("tax_withheld"),
        ),
        Entity(
            "StatutoryTaxCalc",
            label="data_paths.entity.statutory_tax_calc",
            route="/tax-withholding",
            measure=Sum("net_amount"),
        ),
    ),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="WithholdingDeduction.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
        DataPath(
            "oe_contracts",
            "StatutoryTaxCalc",
            via="StatutoryTaxCalc.source_id",
            label="data_paths.entity.progress_claim",
            route="/contracts",
            measure=Sum("net_amount"),
            where=(Where("source_kind", "eq", "progress_claim"),),
            importance="high",
            breaks="data_paths.breaks.no_tax_base",
        ),
        DataPath(
            "oe_subcontractors",
            "StatutoryTaxCalc",
            via="StatutoryTaxCalc.source_id",
            label="data_paths.entity.sub_payment_application",
            route="/subcontractors",
            measure=Sum("net_amount"),
            where=(Where("source_kind", "eq", "sub_payment_application"),),
            importance="high",
            breaks="data_paths.breaks.no_tax_base",
        ),
        DataPath(
            "oe_finance",
            "StatutoryTaxCalc",
            via="StatutoryTaxCalc.source_id",
            label="data_paths.entity.invoice",
            route="/finance",
            measure=Sum("net_amount"),
            where=(Where("source_kind", "eq", "invoice"),),
            importance="high",
            breaks="data_paths.breaks.no_tax_base",
        ),
        DataPath(
            "oe_finance",
            "ReverseChargeDetermination",
            via="ReverseChargeDetermination.invoice_id",
            label="data_paths.entity.reverse_charge",
            route="/finance",
            measure=Sum("net_amount"),
        ),
    ),
)
