# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the methodology module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.methodology",
    entities=(
        Entity("AnalyticDimension", label="data_paths.entity.analytic_dimension"),
        Entity("FundingSource", label="data_paths.entity.funding_source"),
        Entity("Methodology", label="data_paths.entity.methodology"),
        Entity("AnalyticDimensionValue", label="data_paths.entity.analytic_dimension_value"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq",
)
