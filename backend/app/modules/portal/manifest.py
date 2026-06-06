# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Client & Partner Portal manifest."""

from app.core.module_loader import ModuleManifest

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
)
