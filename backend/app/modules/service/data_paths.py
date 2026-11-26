# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the service module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.service",
    entities=(
        Entity("ServiceRecurringSchedule", label="data_paths.entity.service_recurring_schedule"),
        Entity("ServiceContract", label="data_paths.entity.service_contract"),
        Entity("AssetInspectionChecklist", label="data_paths.entity.asset_inspection_checklist"),
        Entity("SLADefinition", label="data_paths.entity.sla_definition"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes service.contract.created, service.contract.terminated, service.recurring.created, service.recurring.materialized, service.sla.breached, service.ticket.awaiting_customer and 13 more; reads code of contacts, ncr",
)
