# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the fx module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.fx",
    entities=(
        Entity("FxPolicy", label="data_paths.entity.fx_policy"),
        Entity("FxRate", label="data_paths.entity.fx_rate"),
        Entity("FxRateSet", label="data_paths.entity.fx_rate_set"),
        Entity("PppFactor", label="data_paths.entity.ppp_factor"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of costs",
)
