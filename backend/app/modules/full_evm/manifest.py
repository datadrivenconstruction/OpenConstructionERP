"""Full EVM module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_full_evm",
    version="0.1.0",
    display_name="Full EVM",
    description="Advanced Earned Value Management with forecasting, S-curves, and TCPI analysis",
    author="OpenEstimate Core Team",
    category="enterprise",
    depends=["oe_finance"],
    auto_install=False,
    enabled=True,
)
