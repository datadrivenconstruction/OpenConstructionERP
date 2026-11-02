# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_russia_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_russia_pack",
    version="1.0.0",
    display_name="Regional Pack - Russia & CIS",
    display_name_i18n={
        "de": "Regionalpaket - Russland & GUS",
        "ru": "Региональный пакет - Россия и СНГ",
    },
    description=(
        "Russian construction standards: GESN/FER/TER cost databases, NDS rates, and Russian contract templates."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["RU", "BY", "KZ", "UZ", "KG"],
    auto_install=False,
    enabled=True,
)
