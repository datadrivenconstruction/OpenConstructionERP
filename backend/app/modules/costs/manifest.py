"""‌⁠‍Cost Database module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_costs",
    version="0.1.0",
    display_name="Cost Database",
    description="Cost item management, rate databases (CWICR, RSMeans, BKI), bulk import",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
)
