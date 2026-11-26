# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the dashboards module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.dashboards",
    entities=(
        Entity("DashboardPreset", label="data_paths.entity.dashboard_preset"),
        Entity("Snapshot", label="data_paths.entity.snapshot"),
        Entity("SnapshotSourceFile", label="data_paths.entity.snapshot_source_file"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of bim_hub",
)
