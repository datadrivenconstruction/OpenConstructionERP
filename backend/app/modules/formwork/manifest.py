"""Formwork module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_formwork",
    version="0.1.0",
    display_name="Formwork",
    description=("Formwork system catalogue + per-BOQ assignments with reuse-aware unit-cost computation"),
    author="OpenConstructionERP Core Team",
    category="estimation",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
