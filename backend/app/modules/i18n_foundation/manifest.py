"""‌⁠‍Module manifest for oe_i18n_foundation."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_i18n_foundation",
    version="0.1.0",
    display_name="Internationalization Foundation",
    description="Multi-currency exchange rates, country registry, work calendars, tax configurations",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
