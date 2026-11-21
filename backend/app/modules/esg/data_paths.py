# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the esg module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.esg",
    roles=(
        "project_manager",
        "site_manager",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.esg.project_manager"),
        Duty("site_manager", "data_paths.duty.esg.site_manager"),
    ),
    entities=(Entity("EsgEntry", label="data_paths.entity.esg_entry", route="/esg"),),
)
