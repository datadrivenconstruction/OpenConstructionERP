# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_us_fl_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_us_fl_pack",
    version="1.0.0",
    display_name="Regional Pack - Florida",
    display_name_i18n={
        "de": "Regionalpaket - Florida",
        "ru": "Региональный пакет - Флорида",
    },
    description=(
        "Florida construction rules on top of the US pack: the contractor as ultimate consumer of materials, "
        "the county surtax cap per item, the local wage preemption, the public retainage cap, the payment "
        "clocks and the notice to owner and claim of lien deadlines."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=["oe_us_pack"],
    auto_install=False,
    enabled=True,
    markets=["US"],
)
