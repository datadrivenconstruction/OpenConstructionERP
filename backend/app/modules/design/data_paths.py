"""Data paths of the design module (see app.core.data_paths).

The model revision drives quantities into the bill of quantities, activities into the schedule,
scope into tender packages and, after acceptance, a change order.
"""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.design",
    roles=("architect", "engineer", "estimator", "planner"),
    entities=(
        Entity("DesignRevision", label="data_paths.entity.design_revision", route="/design"),
        Entity("DesignBrief", label="data_paths.entity.design_brief", route="/design"),
    ),
    outputs=(
        DataPath(
            "oe_boq",
            "DesignEstimateBinding",
            via="DesignEstimateBinding.position_id",
            label="data_paths.entity.position",
            route="/design/estimate",
            importance="high",
            breaks="data_paths.breaks.no_quantities",
        ),
        DataPath(
            "oe_schedule",
            "DesignScheduleBinding",
            via="DesignScheduleBinding.activity_id",
            label="data_paths.entity.activity",
            route="/schedule",
        ),
        DataPath(
            "oe_tendering",
            "DesignTakeoffSection",
            via="DesignTakeoffSection.package_id",
            label="data_paths.entity.tender_package",
            route="/tendering",
        ),
        DataPath(
            "oe_changeorders",
            "DesignChangeOrder",
            via="DesignChangeOrder.change_order_id",
            label="data_paths.entity.change_order",
            route="/changeorders",
        ),
    ),
)
