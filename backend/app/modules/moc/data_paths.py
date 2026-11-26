# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the moc module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.moc",
    entities=(
        Entity("MoCEntry", label="data_paths.entity.mo_c_entry"),
        Entity("MoCImpact", label="data_paths.entity.mo_c_impact"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes bi_dashboards.kpi_recompute, changeorders.candidate_from_moc, moc.entry.auto_proposed, moc.entry.proposed",
)
