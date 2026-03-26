"""Product & Resource Catalog module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_catalog",
    version="0.1.0",
    display_name="Product & Resource Catalog",
    description="Curated catalog of materials, equipment, labor, and operators extracted from cost databases",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_costs"],
    auto_install=True,
    enabled=True,
)
