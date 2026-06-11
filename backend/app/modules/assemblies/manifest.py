"""‌⁠‍Assemblies & Calculations module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_assemblies",
    version="0.1.0",
    display_name="Assemblies & Calculations",
    description=(
        "Composite cost items built from cost database entries with factors. "
        "Supports templates, regional factors, and BOQ integration."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_costs"],
    auto_install=True,
    enabled=True,
)
