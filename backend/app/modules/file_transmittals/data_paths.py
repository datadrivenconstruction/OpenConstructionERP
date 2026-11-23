# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_transmittals module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, External, Where

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
    inputs=(
        DataPath(
            "oe_documents",
            "FileTransmittalItem",
            via="FileTransmittalItem.file_id",
            label="data_paths.entity.document",
            route="/documents",
            where=(Where("file_kind", "eq", "document"),),
            importance="high",
            breaks="data_paths.breaks.nothing_to_send",
        ),
        DataPath(
            "oe_bim_hub",
            "FileTransmittalItem",
            via="FileTransmittalItem.file_id",
            label="data_paths.entity.bim_model",
            route="/bim",
            where=(Where("file_kind", "eq", "bim_model"),),
        ),
        DataPath(
            "oe_takeoff",
            "FileTransmittalItem",
            via="FileTransmittalItem.file_id",
            label="data_paths.entity.takeoff_file",
            route="/takeoff",
            where=(Where("file_kind", "eq", "takeoff"),),
        ),
    ),
)
