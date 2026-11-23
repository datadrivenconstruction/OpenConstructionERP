# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the site_supervision module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, Where

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
    outputs=(
        DataPath(
            "oe_moc",
            "SupervisionEntry",
            via="SupervisionEntry.links_to_change_ref",
            label="data_paths.entity.moc_entry",
            route="/moc",
            where=(Where("links_to_change_ref", "not_null"),),
        ),
    ),
)
