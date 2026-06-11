# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Smart Views module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_smart_views",
    version="1.0.0",
    display_name="Smart Views",
    description=(
        "Rule-based, re-evaluating BIM viewer presets. Selectors run "
        "against canonical element properties at view-load time so a "
        "view authored on one model revision keeps working after the "
        "geometry has been re-imported - and the same view can be "
        "applied to any model that exposes the right properties."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users", "oe_bim_hub"],
    auto_install=True,
    enabled=True,
)
