# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the project_route module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.project_route",
    roles=(
        "project_manager",
        "authority",
        "consultant",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.project_route.project_manager"),
        Duty("authority", "data_paths.duty.project_route.authority"),
        Duty("consultant", "data_paths.duty.project_route.consultant"),
    ),
    entities=(Entity("RouteAssessment", label="data_paths.entity.route_assessment", route="/project-route"),),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="RouteAssessment.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
    ),
)
