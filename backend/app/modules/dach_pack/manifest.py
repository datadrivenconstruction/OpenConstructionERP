# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_dach_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_dach_pack",
    version="1.0.0",
    display_name="Regional Pack - DACH (DE/AT/CH)",
    display_name_i18n={
        "de": "Regionalpaket - DACH (DE/AT/CH)",
        "ru": "Региональный пакет - DACH (DE/AT/CH)",
    },
    description=(
        "DACH construction standards: GAEB XML exchange formats, VOB/B contract terms, "
        "DIN 276 cost groups, HOAI fee schedules, MwSt, and Abschlagsrechnung templates."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["DE", "AT", "CH"],
    auto_install=False,
    enabled=True,
)
