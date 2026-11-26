# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the rfi module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.rfi",
    entities=(
        Entity("RFI", label="data_paths.entity.rfi"),
        Entity("RFIRequestType", label="data_paths.entity.rfi_request_type"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to approval_routes.instance.completed, approval_routes.instance.rejected; publishes rfi.assigned, rfi.closed, rfi.created, rfi.deleted, rfi.responded, rfi.updated; reads code of approval_routes, changeorders, daily_diary, documents",
)
