# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the costs module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum

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
        DataPath(
            "oe_assemblies",
            "Component",
            via="Component.cost_item_id",
            label="data_paths.entity.assembly_component",
            route="/assemblies",
            measure=Sum("total"),
            importance="high",
            breaks="data_paths.breaks.no_assembly_rates",
            scope="global",
        ),
        DataPath(
            "oe_carbon",
            "MaterialCarbonFactor",
            via="MaterialCarbonFactor.cost_item_id",
            label="data_paths.entity.carbon_factor",
            scope="global",
        ),
        DataPath(
            "oe_cost_match",
            "MatchDecision",
            via="MatchDecision.decided_cost_item_id",
            label="data_paths.entity.match_decision",
            scope="global",
        ),
        DataPath(
            "oe_cost_explorer",
            "CostItemResource",
            via="CostItemResource.cost_item_id",
            label="data_paths.entity.cost_resource",
            scope="global",
        ),
    ),
    parameters=(
        Param("CostItem.rate", drives=("oe_boq.Position.unit_rate",), label="data_paths.param.unit_rate"),
        Param("RegionalIndex.factor", drives=("oe_boq.Position.unit_rate",), label="data_paths.param.regional_factor"),
    ),
    inputs=(
        DataPath(
            "oe_rate_feedback",
            "RateFeedbackProposal",
            via="RateFeedbackProposal.cost_item_id",
            label="data_paths.entity.rate_proposal",
            scope="global",
        ),
    ),
)
