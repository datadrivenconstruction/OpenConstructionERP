# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the approval_routes module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.approval_routes",
    entities=(
        Entity("Delegation", label="data_paths.entity.delegation"),
        Entity("Route", label="data_paths.entity.route"),
        Entity("Instance", label="data_paths.entity.instance"),
        Entity("Step", label="data_paths.entity.step"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes approval.escalated, approval.overdue, approval.reassigned, approval_routes.instance.cancelled, approval_routes.instance.started; reads code of ai_agents, notifications, procurement",
)
