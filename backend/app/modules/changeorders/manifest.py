"""Change Orders module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_changeorders",
    version="0.1.0",
    display_name="Change Orders",
    description="Track scope changes, cost impacts, and approval workflows",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
