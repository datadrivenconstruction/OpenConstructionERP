# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Compliance documents tracker module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.compliance_docs.data_paths import DATA_PATHS

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
    data_paths=DATA_PATHS,
)
