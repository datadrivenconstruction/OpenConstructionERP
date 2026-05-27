"""‌⁠‍CRM module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_crm",
    version="0.1.0",
    display_name="CRM Sales Pipeline",
    description=("Sales pipeline: accounts, leads, opportunities, activities, forecasting, win/loss analytics"),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
