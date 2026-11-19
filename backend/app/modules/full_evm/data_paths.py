# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the full_evm module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum

DATA_PATHS = DataPaths(
    why="data_paths.why.full_evm",
    roles=(
        "planner",
        "quantity_surveyor",
        "client",
    ),
    entities=(
        Entity("EVMBaseline", label="data_paths.entity.evm_baseline", route="/evm", measure=Sum("bac")),
        Entity("EVMMeasure", label="data_paths.entity.evm_measure", route="/evm"),
        Entity("EVMForecast", label="data_paths.entity.evm_forecast", route="/evm"),
    ),
    inputs=(
        DataPath(
            "oe_schedule",
            "Activity",
            via="Activity.progress_pct",
            label="data_paths.entity.activity",
            route="/schedule",
            importance="critical",
            breaks="data_paths.breaks.no_evm",
        ),
        DataPath(
            "oe_costmodel",
            "BudgetLine",
            via="BudgetLine.actual_amount",
            label="data_paths.entity.budget_line",
            route="/cost-model",
            importance="critical",
            breaks="data_paths.breaks.no_evm",
        ),
    ),
    parameters=(
        Param(
            "EVMMeasure.eac_method",
            drives=(
                "EVMMeasure.eac",
                "EVMMeasure.vac",
            ),
            label="data_paths.param.eac_method",
        ),
    ),
)
