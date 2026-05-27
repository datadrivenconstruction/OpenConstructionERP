"""‌⁠‍HSE Advanced module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_hse_advanced",
    version="0.1.0",
    display_name="HSE Advanced",
    description=("HSE/EHS: JSA, permit-to-work, toolbox talks, PPE, audits, CAPA, KPI (TRIR/LTIFR) — sister to safety"),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
