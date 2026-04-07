"""Module manifest for oe_india_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_india_pack",
    version="1.0.0",
    display_name="Regional Pack — India",
    display_name_i18n={
        "de": "Regionalpaket — Indien",
        "ru": "Региональный пакет — Индия",
    },
    description=(
        "Indian construction standards: IS codes, CPWD/MES rate references, "
        "multi-rate GST (28/18/12/5/0%), INR, and Indian contract forms."
    ),
    author="OpenEstimate Core Team",
    category="regional",
    depends=[],
    auto_install=False,
    enabled=True,
)
