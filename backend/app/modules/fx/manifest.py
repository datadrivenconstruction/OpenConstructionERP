"""Currency / FX module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_fx",
    version="0.1.0",
    display_name="Currency / FX",
    description="Live ECB foreign-exchange rates and optional PPP conversion for multi-currency cost bases and estimates",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_costs"],
    auto_install=True,
    enabled=True,
)
