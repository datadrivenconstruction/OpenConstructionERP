# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the norm_expansion module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.norm_expansion",
    entities=(
        Entity("ProductionNorm", label="data_paths.entity.production_norm"),
        Entity("NormMaterial", label="data_paths.entity.norm_material"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of assemblies, costs, labor_rates, price_breakdown, waste_factors",
)
