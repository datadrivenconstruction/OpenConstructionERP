# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the interface_management module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.interface_management",
    roles=(
        "project_manager",
        "subcontractor",
        "planner",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.interface_management.project_manager"),
        Duty("subcontractor", "data_paths.duty.interface_management.subcontractor"),
        Duty("planner", "data_paths.duty.interface_management.planner"),
    ),
    entities=(
        Entity("InterfaceRecord", label="data_paths.entity.interface", route="/interface-management"),
        Entity("InterfaceAction", label="data_paths.entity.interface_action", route="/interface-management"),
    ),
    inputs=(
        DataPath(
            "oe_rfi",
            "InterfaceRecord",
            via="InterfaceRecord.rfi_id",
            label="data_paths.entity.rfi",
            where=(Where("rfi_id", "not_null"),),
        ),
        DataPath(
            "oe_schedule",
            "InterfaceRecord",
            via="InterfaceRecord.schedule_activity_id",
            label="data_paths.entity.activity",
            importance="high",
            breaks="data_paths.breaks.interface_date_unlinked",
            where=(Where("schedule_activity_id", "not_null"),),
        ),
        DataPath(
            "oe_subcontractors",
            "InterfaceRecord",
            via="InterfaceRecord.owner_subcontractor_id",
            label="data_paths.entity.subcontractor",
            where=(Where("owner_subcontractor_id", "not_null"),),
        ),
    ),
)
