"""Module manifest for oe_us_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_us_pack",
    version="1.0.0",
    display_name="Regional Pack — United States",
    display_name_i18n={
        "de": "Regionalpaket — Vereinigte Staaten",
        "ru": "Региональный пакет — США",
    },
    description=(
        "US construction standards: AIA G702 payment applications, "
        "CSI MasterFormat divisions, imperial units, USD, and state sales-tax examples."
    ),
    author="OpenEstimate Core Team",
    category="regional",
    depends=[],
    auto_install=False,
    enabled=True,
)
