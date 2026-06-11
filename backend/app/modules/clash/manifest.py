# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash detection module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_clash",
    version="1.0.0",
    display_name="Clash Detection",
    description=(
        "Geometric AABB interference / clearance detection over canonical "
        "BIM elements, with a discipline×discipline clash matrix, a review "
        "workflow and one-click BCF export - no IfcOpenShell."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users", "oe_bim_hub", "oe_bcf"],
    auto_install=True,
    enabled=True,
)
