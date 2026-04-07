"""BIM Hub module manifest — BIM data management backend."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_bim_hub",
    version="0.1.0",
    display_name="BIM Hub",
    description="BIM data management: models, elements, BOQ linking, quantity maps, and model diffs",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
