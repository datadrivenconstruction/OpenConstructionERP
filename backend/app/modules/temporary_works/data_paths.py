# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the temporary_works module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.temporary_works",
    roles=(
        "engineer",
        "site_manager",
        "inspector",
    ),
    duties=(
        Duty("engineer", "data_paths.duty.temporary_works.engineer"),
        Duty("site_manager", "data_paths.duty.temporary_works.site_manager"),
        Duty("inspector", "data_paths.duty.temporary_works.inspector"),
    ),
    entities=(
        Entity("TemporaryWorksItem", label="data_paths.entity.temporary_works_item", route="/temporary-works"),
        Entity("TemporaryWorksPermit", label="data_paths.entity.temporary_works_permit", route="/temporary-works"),
    ),
    inputs=(
        DataPath(
            "oe_projects",
            "Project",
            via="TemporaryWorksItem.project_id",
            label="data_paths.entity.project",
            route="/projects",
        ),
    ),
)
