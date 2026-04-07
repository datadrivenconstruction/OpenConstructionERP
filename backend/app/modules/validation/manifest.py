"""Validation Engine module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_validation",
    version="1.0.0",
    display_name="Validation Engine",
    description=("Data quality validation with configurable rule sets (DIN 276, GAEB, NRM, MasterFormat, BOQ quality)"),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
