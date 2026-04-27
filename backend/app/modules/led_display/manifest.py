"""LED Display module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_led_display",
    version="0.1.0",
    display_name="LED Display Management",
    description="Manage LED display projects for construction and infrastructure initiatives - from planning and procurement to installation and ongoing maintenance",
    author="OpenEstimate Core Team",
    category="core",  # core, integration, regional, community
    depends=["oe_users", "oe_projects", "oe_procurement", "oe_schedule"],
    auto_install=False,
    enabled=True,
)