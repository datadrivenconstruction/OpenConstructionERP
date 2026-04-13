"""ERP Chat module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_erp_chat",
    version="0.1.0",
    display_name="ERP Chat",
    description="AI-powered chat with tool-calling for construction ERP data",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_ai", "oe_projects"],
    auto_install=True,
    enabled=True,
)
