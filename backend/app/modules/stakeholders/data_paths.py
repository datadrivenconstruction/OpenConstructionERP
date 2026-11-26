# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the stakeholders module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.stakeholders",
    entities=(
        Entity("CommunicationPlanItem", label="data_paths.entity.communication_plan_item"),
        Entity("GovernanceBody", label="data_paths.entity.governance_body"),
        Entity("Mandate", label="data_paths.entity.mandate"),
        Entity("ProjectRole", label="data_paths.entity.project_role"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to approval_routes.instance.cancelled, approval_routes.instance.completed, approval_routes.instance.rejected; publishes mandate.changed, role.changed, stakeholder.assessed, stakeholder.created; reads code of approval_routes, cde, contacts, correspondence, meetings, notifications and 4 more",
)
