# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the site_supervision module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.site_supervision",
    roles=(
        "inspector",
        "site_manager",
        "contractor",
    ),
    duties=(
        Duty("inspector", "data_paths.duty.site_supervision.inspector"),
        Duty("site_manager", "data_paths.duty.site_supervision.site_manager"),
        Duty("contractor", "data_paths.duty.site_supervision.contractor"),
    ),
    entities=(
        Entity("SupervisionVisit", label="data_paths.entity.supervision_visit", route="/site-supervision"),
        Entity("SupervisionEntry", label="data_paths.entity.supervision_entry", route="/site-supervision"),
    ),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="SupervisionVisit.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
    ),
)
