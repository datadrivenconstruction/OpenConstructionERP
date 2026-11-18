# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_us_ny_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_us_ny_pack",
    version="1.0.0",
    display_name="Regional Pack - New York",
    display_name_i18n={
        "de": "Regionalpaket - New York",
        "ru": "Региональный пакет - Нью-Йорк",
    },
    description=(
        "New York construction rules on top of the US pack: the capital improvement and repair split that "
        "decides who pays sales tax, prevailing wage schedules and electronic certified payroll, the private "
        "and public retainage caps, the payment clocks and the mechanic's lien filing window."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=["oe_us_pack"],
    auto_install=False,
    enabled=True,
    markets=["US"],
)
