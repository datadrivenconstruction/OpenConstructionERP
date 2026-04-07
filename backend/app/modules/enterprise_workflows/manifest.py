"""Enterprise Workflows module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_enterprise_workflows",
    version="0.1.0",
    display_name="Enterprise Workflows",
    description="Configurable approval workflows for invoices, purchase orders, variations, and BOQs",
    author="OpenEstimate Core Team",
    category="enterprise",
    depends=["oe_users", "oe_projects"],
    auto_install=False,
    enabled=True,
)
