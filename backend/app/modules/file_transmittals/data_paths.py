# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_transmittals module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity, External

DATA_PATHS = DataPaths(
    why="data_paths.why.file_transmittals",
    roles=(
        "project_manager",
        "contractor",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.file_transmittals.project_manager"),
        Duty("contractor", "data_paths.duty.file_transmittals.contractor"),
    ),
    external=(External("party", "data_paths.external.transmittal_recipients"),),
    entities=(
        Entity("FileTransmittal", label="data_paths.entity.file_transmittal", route="/files/transmittals"),
        Entity("FileTransmittalItem", label="data_paths.entity.transmittal_item", route="/files/transmittals"),
    ),
)
