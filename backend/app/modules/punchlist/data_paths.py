# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the punchlist module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.punchlist",
    entities=(Entity("PunchItem", label="data_paths.entity.punch_item"),),
    reason="No foreign key joins its tables to another module's tables; subscribes to clash.high_severity.detected, inspection.completed.failed, property_dev.snag.created; publishes punchlist.item.created, punchlist.item.deleted, punchlist.item.status_changed, punchlist.item.updated; reads code of bcf, contracts, documents, property_dev",
)
