"""‌⁠‍Procurement module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_procurement",
    version="0.1.0",
    display_name="Procurement",
    description="Purchase orders, goods receipts, and vendor management for construction projects",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
)
