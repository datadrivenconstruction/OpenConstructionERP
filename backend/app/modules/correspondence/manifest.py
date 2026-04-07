"""Correspondence module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_correspondence",
    version="0.1.0",
    display_name="Correspondence",
    description="Project correspondence tracking — letters, emails, notices with direction, contacts, and document cross-references",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
)
