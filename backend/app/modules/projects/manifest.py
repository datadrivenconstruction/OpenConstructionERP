"""Projects module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_projects",
    version="0.1.0",
    display_name="Projects",
    description="Project management with regional settings, classification standards, and validation configuration",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
