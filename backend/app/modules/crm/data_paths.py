# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the crm module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.crm",
    entities=(
        Entity("Opportunity", label="data_paths.entity.opportunity"),
        Entity("Account", label="data_paths.entity.account"),
        Entity("Forecast", label="data_paths.entity.forecast"),
        Entity("PipelineStage", label="data_paths.entity.pipeline_stage"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes crm.lead.converted, crm.opportunity.lost, crm.opportunity.scored, crm.opportunity.stage_changed; reads code of contacts, schedule",
)
