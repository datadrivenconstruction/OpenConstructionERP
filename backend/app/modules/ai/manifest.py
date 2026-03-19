"""AI Estimation module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_ai",
    version="0.1.0",
    display_name="AI Estimation",
    description="AI-powered construction cost estimation from text descriptions and photos",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_boq", "oe_projects"],
    auto_install=True,
    enabled=True,
)
