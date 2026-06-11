"""‌⁠‍Module manifest for oe_asia_pac_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_asia_pac_pack",
    version="1.0.0",
    display_name="Regional Pack - Asia-Pacific",
    display_name_i18n={
        "de": "Regionalpaket - Asien-Pazifik",
        "ru": "Региональный пакет - Азиатско-Тихоокеанский регион",
    },
    description=(
        "Asia-Pacific construction standards: AIQS/Rawlinsons (AU), NATSPEC, "
        "Japanese sekkisan standards, Singapore BCA references, "
        "and multi-currency support (AUD/NZD/JPY/SGD)."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    auto_install=False,
    enabled=True,
)
