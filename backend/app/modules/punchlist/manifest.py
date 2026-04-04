"""Punch List module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_punchlist",
    version="0.1.0",
    display_name="Punch List",
    description="Track construction deficiencies, quality issues, and snag items with photo evidence and verification workflows",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
