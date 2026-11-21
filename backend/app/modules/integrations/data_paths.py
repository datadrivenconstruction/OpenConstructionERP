# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the integrations module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity, External

DATA_PATHS = DataPaths(
    why="data_paths.why.integrations",
    roles=("project_manager",),
    duties=(Duty("project_manager", "data_paths.duty.integrations.project_manager"),),
    external=(External("device", "data_paths.external.external_systems"),),
    entities=(
        Entity("WebhookEndpoint", label="data_paths.entity.webhook", route="/integrations"),
        Entity("WebhookDelivery", label="data_paths.entity.webhook_delivery", route="/integrations"),
        Entity("IntegrationConfig", label="data_paths.entity.integration_config", route="/integrations"),
    ),
)
