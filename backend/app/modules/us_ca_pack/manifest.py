# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_us_ca_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_us_ca_pack",
    version="1.0.0",
    display_name="Regional Pack - California",
    display_name_i18n={
        "de": "Regionalpaket - Kalifornien",
        "ru": "Региональный пакет - Калифорния",
    },
    description=(
        "California construction rules on top of the US pack: the district sales tax stack and the split "
        "between materials the contractor consumes and fixtures it sells, the state prevailing wage regime "
        "and its thresholds, the public and private retention caps, and the statutory payment and lien clocks."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=["oe_us_pack"],
    markets=["US"],
    auto_install=False,
    enabled=True,
)
