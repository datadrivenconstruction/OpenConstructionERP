# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_latam_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_latam_pack",
    version="1.0.0",
    display_name="Regional Pack - Latin America",
    display_name_i18n={
        "de": "Regionalpaket - Lateinamerika",
        "ru": "Региональный пакет - Латинская Америка",
    },
    description=(
        "Latin America construction standards: SINAPI (Brazil), NTDIF (Mexico), "
        "multi-currency support (BRL/MXN/ARS), and regional contract forms."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["BR", "MX", "AR", "CL", "CO", "PE"],
    auto_install=False,
    enabled=True,
)
