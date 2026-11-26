# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Client & Partner Portal manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.portal.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_portal",
    version="0.1.0",
    display_name="Client & Partner Portal",
    description=(
        "External portal users (clients/investors/consultants/subcontractors/"
        "suppliers/building users) with magic-link auth, RLS, notifications, "
        "audit log"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
