# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the price_index module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.price_index",
    entities=(
        Entity("CostIndexSeries", label="data_paths.entity.cost_index_series"),
        Entity("LocationFactor", label="data_paths.entity.location_factor"),
        Entity("PriceIndexSeedMarker", label="data_paths.entity.price_index_seed_marker"),
        Entity("ResourceIndexValue", label="data_paths.entity.resource_index_value"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, costs, i18n_foundation",
)
