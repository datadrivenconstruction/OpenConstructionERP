# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the costs module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param

DATA_PATHS = DataPaths(
    why="data_paths.why.costs",
    roles=("estimator",),
    entities=(
        Entity("CostItem", label="data_paths.entity.cost_item", route="/costs", scope="global"),
        Entity("CostItemUsage", label="data_paths.entity.cost_item_usage", route="/costs"),
    ),
    outputs=(
        DataPath(
            "oe_boq",
            "CostItemUsage",
            via="CostItemUsage.cost_item_id",
            label="data_paths.entity.position",
            route="/boq",
            importance="high",
            breaks="data_paths.breaks.no_prices",
        ),
    ),
    parameters=(
        Param("CostItem.rate", drives=("oe_boq.Position.unit_rate",), label="data_paths.param.unit_rate"),
        Param("RegionalIndex.factor", drives=("oe_boq.Position.unit_rate",), label="data_paths.param.regional_factor"),
    ),
)
