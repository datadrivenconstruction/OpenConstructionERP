# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integrations module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.integrations.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_integrations",
    version="0.1.0",
    display_name="Integrations",
    description="Chat connectors (Teams, Slack, Telegram), outgoing webhooks, email, iCal feeds",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
