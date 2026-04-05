"""Field Reports module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_fieldreports",
    version="0.1.0",
    display_name="Field Reports",
    description="Daily field reports for construction sites — weather, workforce, delays, safety incidents, and approvals",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
