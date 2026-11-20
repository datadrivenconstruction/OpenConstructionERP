# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the pointcloud module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.pointcloud",
    roles=("surveyor", "engineer", "inspector"),
    duties=(
        Duty("surveyor", "data_paths.duty.pointcloud.surveyor"),
        Duty("engineer", "data_paths.duty.pointcloud.engineer"),
        Duty("inspector", "data_paths.duty.pointcloud.inspector"),
    ),
    external=(External("file", "data_paths.external.scan_files"),),
    entities=(Entity("ScanDataset", label="data_paths.entity.scan", route="/pointcloud"),),
    outputs=(
        DataPath(
            "oe_construction_control",
            "AsBuiltRecord",
            via="AsBuiltRecord.source_ref",
            label="data_paths.entity.asbuilt_record",
            route="/construction-control",
            importance="high",
            breaks="data_paths.breaks.no_as_built_check",
            where=(Where("source_kind", "in", ("pointcloud_scan", "pointcloud_registration")),),
        ),
    ),
)
