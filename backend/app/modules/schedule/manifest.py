"""4D Schedule module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_schedule",
    version="0.1.0",
    display_name="4D Schedule",
    description="4D construction scheduling — linking BOQ positions to a timeline",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
