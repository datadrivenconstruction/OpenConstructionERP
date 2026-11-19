# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the ncr module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.ncr",
    roles=(
        "inspector",
        "site_manager",
        "subcontractor",
    ),
    entities=(
        Entity("NCR", label="data_paths.entity.ncr", route="/ncr"),
        Entity("NCR", label="data_paths.entity.open_ncr", route="/ncr", where=(Where("status", "ne", "closed"),)),
    ),
    inputs=(
        DataPath(
            "oe_construction_control",
            "NCR",
            via="NCR.linked_inspection_id",
            label="data_paths.entity.inspection",
            route="/construction-control",
            importance="high",
            breaks="data_paths.breaks.no_defect_trail",
        ),
    ),
    outputs=(
        DataPath(
            "oe_changeorders",
            "NCR",
            via="NCR.change_order_id",
            label="data_paths.entity.change_order",
            route="/changeorders",
            importance="high",
            breaks="data_paths.breaks.no_cost_recovery",
        ),
    ),
    parameters=(
        Param(
            "NCR.cost_impact", drives=("oe_changeorders.ChangeOrder.cost_impact",), label="data_paths.param.cost_impact"
        ),
    ),
)
