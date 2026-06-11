"""‌⁠‍Tendering module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_tendering",
    version="0.1.0",
    display_name="Tendering",
    description="Bid package management, distribution, collection, and comparison",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
