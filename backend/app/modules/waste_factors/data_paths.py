# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the waste_factors module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity, Param

DATA_PATHS = DataPaths(
    why="data_paths.why.waste_factors",
    roles=(
        "estimator",
        "quantity_surveyor",
    ),
    duties=(
        Duty("estimator", "data_paths.duty.waste_factors.estimator"),
        Duty("quantity_surveyor", "data_paths.duty.waste_factors.quantity_surveyor"),
    ),
    entities=(Entity("WasteFactor", label="data_paths.entity.waste_factor", route="/waste-factors", scope="global"),),
    parameters=(
        Param(
            "WasteFactor.factor", drives=("oe_norm_expansion:material_waste",), label="data_paths.param.waste_factor"
        ),
    ),
)
