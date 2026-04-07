"""Finance module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_finance",
    version="0.1.0",
    display_name="Finance",
    description="Invoicing, payments, budgets, and Earned Value Management for construction projects",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
)
