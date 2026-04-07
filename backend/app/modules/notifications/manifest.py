"""Notifications module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_notifications",
    version="0.1.0",
    display_name="Notifications",
    description="In-app notification system with i18n keys and per-user preferences",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
