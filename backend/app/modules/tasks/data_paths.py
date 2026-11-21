# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the tasks module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.tasks",
    roles=(
        "project_manager",
        "site_manager",
        "contractor",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.tasks.project_manager"),
        Duty("site_manager", "data_paths.duty.tasks.site_manager"),
        Duty("contractor", "data_paths.duty.tasks.contractor"),
    ),
    entities=(Entity("Task", label="data_paths.entity.task", route="/tasks"),),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="Task.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
        DataPath(
            "oe_contacts",
            "Contact",
            via="Task.metadata_.assignee_contact_id",
            label="data_paths.entity.contact",
            route="/contacts",
        ),
    ),
)
