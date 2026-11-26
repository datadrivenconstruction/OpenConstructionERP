# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the hse_frame module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.hse_frame",
    entities=(
        Entity("HseFrame", label="data_paths.entity.hse_frame"),
        Entity("HseItem", label="data_paths.entity.hse_item"),
        Entity("HseLink", label="data_paths.entity.hse_link"),
        Entity("HseRole", label="data_paths.entity.hse_role"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes frame.approved, frame.binding, frame.revising, frame.submitted; reads code of construction_control, hse_advanced, inspections, permits, project_governance, safety",
)
