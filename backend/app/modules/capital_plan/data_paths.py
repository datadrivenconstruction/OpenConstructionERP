# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the capital_plan module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.capital_plan",
    entities=(
        Entity("CapitalPlanItem", label="data_paths.entity.capital_plan_item"),
        Entity("CapitalPlan", label="data_paths.entity.capital_plan"),
        Entity("CapitalPlanEnvelope", label="data_paths.entity.capital_plan_envelope"),
        Entity("CapitalPlanScenario", label="data_paths.entity.capital_plan_scenario"),
    ),
    inputs=(
        DataPath("oe_portfolio", "CapitalPlan", via="CapitalPlan.node_id", label="data_paths.entity.portfolio_node"),
    ),
)
