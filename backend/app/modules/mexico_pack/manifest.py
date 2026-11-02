# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_mexico_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_mexico_pack",
    version="1.0.0",
    display_name="Regional Pack - Mexico",
    display_name_i18n={
        "es": "Paquete regional - Mexico",
        "de": "Regionalpaket - Mexiko",
        "ru": "Региональный пакет - Мексика",
    },
    description=(
        "Mexican construction standards: APU unit-price analysis (materiales, "
        "mano de obra, maquinaria, indirectos, financiamiento, utilidad and "
        "cargos adicionales) under the LOPSRM public-works law, IVA 16 percent "
        "with the 8 percent border region and IVA/ISR retenciones, CFDI 4.0 "
        "invoicing fields, social-housing bodies (INFONAVIT, FOVISSSTE, CONAVI), "
        "IMSS and NOM-031-STPS site safety, 32 states and MXN."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["MX"],
    auto_install=False,
    enabled=True,
)
