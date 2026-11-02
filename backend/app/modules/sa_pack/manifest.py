# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_sa_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_sa_pack",
    version="1.0.0",
    display_name="Regional Pack - South Africa",
    display_name_i18n={
        "de": "Regionalpaket - Südafrika",
        "ru": "Региональный пакет - Южная Африка",
    },
    description=(
        "South African construction standards: SANS 1200 civil works and ASAQS "
        "building measurement, CIDB contractor grading, PPPFA 80/20 and 90/10 "
        "preferential procurement scoring, National Treasury infrastructure "
        "delivery gates, ZAR and 15 percent VAT."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["ZA"],
    auto_install=False,
    enabled=True,
)
