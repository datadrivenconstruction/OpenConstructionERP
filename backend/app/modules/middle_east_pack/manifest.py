# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_middle_east_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_middle_east_pack",
    version="1.0.0",
    display_name="Regional Pack - Middle East & GCC",
    display_name_i18n={
        "de": "Regionalpaket - Naher Osten & GCC",
        "ru": "Региональный пакет - Ближний Восток и GCC",
    },
    description=(
        "Middle East / GCC construction standards: FIDIC contract forms, "
        "Islamic calendar references, Ramadan adjustments, GCC VAT rates, "
        "bilingual PDF support (Arabic + English)."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["AE", "SA", "QA", "KW", "BH", "OM", "JO", "EG"],
    auto_install=False,
    enabled=True,
)
