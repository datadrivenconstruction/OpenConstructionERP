# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the site_prep module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.site_prep",
    roles=(
        "site_manager",
        "project_manager",
        "authority",
    ),
    duties=(
        Duty("site_manager", "data_paths.duty.site_prep.site_manager"),
        Duty("project_manager", "data_paths.duty.site_prep.project_manager"),
        Duty("authority", "data_paths.duty.site_prep.authority"),
    ),
    entities=(
        Entity("SitePrepPlan", label="data_paths.entity.site_prep_plan", route="/site-prep"),
        Entity("SitePrepItem", label="data_paths.entity.site_prep_item", route="/site-prep"),
    ),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="SitePrepPlan.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
    ),
)
