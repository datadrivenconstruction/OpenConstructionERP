"""Integrations module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_integrations",
    version="0.1.0",
    display_name="Integrations",
    description="Chat connectors (Teams, Slack, Telegram), outgoing webhooks, email, iCal feeds",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
