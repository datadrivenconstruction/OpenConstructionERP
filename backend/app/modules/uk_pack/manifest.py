"""Module manifest for oe_uk_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_uk_pack",
    version="1.0.0",
    display_name="Regional Pack — United Kingdom",
    display_name_i18n={
        "de": "Regionalpaket — Vereinigtes Königreich",
        "ru": "Региональный пакет — Великобритания",
    },
    description=(
        "UK construction standards: JCT/NEC4 contract forms, NRM2 measurement rules, "
        "CIS tax deductions, Interim Valuations, VAT rates, and GBP."
    ),
    author="OpenEstimate Core Team",
    category="regional",
    depends=[],
    auto_install=False,
    enabled=True,
)
