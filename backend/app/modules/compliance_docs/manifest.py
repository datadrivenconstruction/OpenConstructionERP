# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Compliance documents tracker module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_compliance_docs",
    version="0.1.0",
    display_name="Compliance Documents",
    description=(
        "Track expiring insurance policies, permits, bonds and "
        "certifications per project with reminder windows and a "
        "convenience expiring-soon endpoint for dashboards."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
