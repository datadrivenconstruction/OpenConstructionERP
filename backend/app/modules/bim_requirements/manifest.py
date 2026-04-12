"""BIM Requirements Import/Export module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_bim_requirements",
    version="1.0.0",
    display_name="BIM Requirements",
    description=(
        "Universal import/export for BIM requirement formats: "
        "IDS XML, COBie, Excel/CSV, Revit Shared Parameters, BIMQ JSON"
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
