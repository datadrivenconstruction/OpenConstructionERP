"""Risk Register module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_risk",
    version="0.1.0",
    display_name="Risk Register",
    description="Track project risks, assess probability and impact, manage mitigation strategies",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
