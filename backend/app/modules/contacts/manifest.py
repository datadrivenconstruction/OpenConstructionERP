"""Contacts Directory module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_contacts",
    version="0.1.0",
    display_name="Contacts Directory",
    description="Unified contacts directory for clients, subcontractors, suppliers, consultants",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
