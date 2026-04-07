"""Team Visibility module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_teams",
    version="0.1.0",
    display_name="Team Visibility",
    description="Team-based entity visibility and access control within projects",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
