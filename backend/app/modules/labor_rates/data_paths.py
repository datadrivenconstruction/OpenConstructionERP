# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the labor_rates module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.labor_rates",
    entities=(
        Entity("CrewMember", label="data_paths.entity.crew_member"),
        Entity("LaborRateTemplate", label="data_paths.entity.labor_rate_template"),
        Entity("OnCostComponent", label="data_paths.entity.on_cost_component"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of assemblies, costs, price_breakdown",
)
