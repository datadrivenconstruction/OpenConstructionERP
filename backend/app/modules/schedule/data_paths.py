# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the schedule module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Stale, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.schedule",
    roles=(
        "planner",
        "site_manager",
    ),
    entities=(
        Entity("Schedule", label="data_paths.entity.schedule", route="/schedule"),
        Entity("Activity", label="data_paths.entity.activity", route="/schedule"),
        Entity(
            "Activity",
            label="data_paths.entity.critical_activity",
            route="/schedule",
            where=(Where("is_critical", "eq", True),),
        ),
        Entity("ScheduleBaseline", label="data_paths.entity.baseline", route="/schedule"),
        Entity("WorkOrder", label="data_paths.entity.work_order", route="/schedule"),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "Activity",
            via="Activity.boq_position_ids",
            label="data_paths.entity.position",
            route="/boq",
            importance="high",
            breaks="data_paths.breaks.no_cost_loading",
        ),
        DataPath(
            "oe_boq",
            "WorkOrder",
            via="WorkOrder.boq_position_id",
            label="data_paths.entity.work_order",
            route="/boq",
        ),
    ),
    outputs=(
        DataPath(
            "oe_contracts",
            "ContractMilestone",
            via="ContractMilestone.activity_id",
            label="data_paths.entity.milestone",
            route="/contracts",
            importance="high",
            breaks="data_paths.breaks.no_payment_milestone",
        ),
        DataPath(
            "oe_costmodel",
            "BudgetLine",
            via="BudgetLine.activity_id",
            label="data_paths.entity.budget_line",
            route="/cost-model",
        ),
        DataPath(
            "oe_procurement",
            "MaterialRequisitionItem",
            via="MaterialRequisitionItem.schedule_activity_id",
            label="data_paths.entity.requisition",
            route="/procurement",
        ),
    ),
    parameters=(
        Param(
            "Activity.duration_days",
            drives=(
                "Activity.end_date",
                "Activity.total_float",
            ),
            label="data_paths.param.duration",
        ),
        Param("Activity.progress_pct", drives=("oe_full_evm:earned_value",), label="data_paths.param.progress"),
        Param(
            "Activity.cost_planned",
            drives=(
                "oe_costmodel:cash_flow",
                "oe_costmodel.BudgetLine.planned_amount",
            ),
            label="data_paths.param.planned_cost",
        ),
    ),
    stale=(
        Stale(
            source="oe_boq.Position.updated_at",
            copy="ScheduleBaseline.baseline_date",
            label="data_paths.stale.changed_after_baseline",
        ),
    ),
)
