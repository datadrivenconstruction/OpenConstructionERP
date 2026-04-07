"""Meetings module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_meetings",
    version="0.1.0",
    display_name="Meetings",
    description="Meeting minutes management — agendas, attendees, action items, and status tracking",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
