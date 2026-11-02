# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_china_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_china_pack",
    version="1.0.0",
    display_name="Regional Pack - China",
    display_name_i18n={
        "de": "Regionalpaket - China",
        "ru": "Региональный пакет - Китай",
        "zh": "中国区域包",
    },
    description=(
        "Chinese construction standards: GB 50500 bill of quantities valuation, "
        "the GB 50854-50862 measurement family, national and provincial quotas, "
        "VAT (13/9/6/3%), CNY, and Chinese model contract forms."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["CN"],
    auto_install=False,
    enabled=True,
)
