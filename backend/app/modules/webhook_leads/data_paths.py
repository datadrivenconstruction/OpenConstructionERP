# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the webhook_leads module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.webhook_leads",
    entities=(
        Entity("WebhookSource", label="data_paths.entity.webhook_source"),
        Entity("PayloadMapping", label="data_paths.entity.payload_mapping"),
        Entity("WebhookLog", label="data_paths.entity.webhook_log"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of crm",
)
