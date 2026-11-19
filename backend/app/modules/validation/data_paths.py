# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the validation module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.validation",
    roles=(
        "estimator",
        "engineer",
    ),
    entities=(Entity("ValidationReport", label="data_paths.entity.validation_report", route="/validation"),),
    inputs=(
        DataPath(
            "oe_boq",
            "Position",
            via="Position.validation_status",
            label="data_paths.entity.unchecked_position",
            route="/boq",
            where=(Where("validation_status", "in", ("warnings", "errors")),),
        ),
    ),
    outputs=(
        DataPath(
            "oe_boq",
            "ValidationReport",
            via="ValidationReport.target_id",
            label="data_paths.entity.validation_report",
            route="/boq",
        ),
    ),
    parameters=(
        Param(
            "ValidationReport.rule_set",
            drives=(
                "ValidationReport.score",
                "oe_boq.Position.validation_status",
            ),
            label="data_paths.param.rule_set",
        ),
    ),
)
