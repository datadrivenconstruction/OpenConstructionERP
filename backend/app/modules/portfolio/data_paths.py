# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the portfolio module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.portfolio",
    entities=(
        Entity("PortfolioMembership", label="data_paths.entity.portfolio_membership"),
        Entity("PortfolioCrossLink", label="data_paths.entity.portfolio_cross_link"),
        Entity("PortfolioNode", label="data_paths.entity.portfolio_node"),
    ),
    outputs=(
        DataPath("oe_capital_plan", "CapitalPlan", via="CapitalPlan.node_id", label="data_paths.entity.capital_plan"),
    ),
)
