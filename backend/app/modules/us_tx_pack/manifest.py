# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_us_tx_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_us_tx_pack",
    version="1.0.0",
    display_name="Regional Pack - Texas",
    display_name_i18n={
        "de": "Regionalpaket - Texas",
        "ru": "Региональный пакет - Техас",
    },
    description=(
        "Texas construction rules on top of the US pack: how a lump sum contract and a separated contract "
        "split the sales tax on materials, the locally determined prevailing wage, the public works retainage "
        "caps and their contract-value threshold, and the statutory payment and lien clocks."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=["oe_us_pack"],
    markets=["US"],
    auto_install=False,
    enabled=True,
)
