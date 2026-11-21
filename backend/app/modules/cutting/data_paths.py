# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cutting module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.cutting",
    roles=(
        "site_manager",
        "estimator",
        "buyer",
    ),
    duties=(
        Duty("site_manager", "data_paths.duty.cutting.site_manager"),
        Duty("estimator", "data_paths.duty.cutting.estimator"),
        Duty("buyer", "data_paths.duty.cutting.buyer"),
    ),
    external=(External("file", "data_paths.external.cut_list_files"),),
    entities=(
        Entity("CuttingJob", label="data_paths.entity.cutting_job", route="/cutting"),
        Entity("CuttingPlan", label="data_paths.entity.cutting_plan", route="/cutting"),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "CuttingJob",
            via="CuttingJob.boq_position_id",
            label="data_paths.entity.position",
            importance="high",
            breaks="data_paths.breaks.no_cut_quantity",
            where=(Where("boq_position_id", "not_null"),),
        ),
        DataPath(
            "oe_rebar_schedule",
            "CuttingJob",
            via="CuttingJob.source_ref",
            label="data_paths.entity.rebar_schedule",
            where=(Where("source_type", "eq", "rebar_schedule"),),
        ),
    ),
    outputs=(
        DataPath(
            "oe_procurement",
            "CuttingJob",
            via="CuttingJob.procurement_req_item_id",
            label="data_paths.entity.requisition",
            importance="high",
            breaks="data_paths.breaks.stock_not_ordered",
            where=(Where("procurement_req_item_id", "not_null"),),
        ),
    ),
)
