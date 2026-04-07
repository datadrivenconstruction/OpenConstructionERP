"""Transmittals module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_transmittals",
    version="0.1.0",
    display_name="Transmittals",
    description="Formal document transmittal management with recipients, acknowledgements, and responses",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
)
