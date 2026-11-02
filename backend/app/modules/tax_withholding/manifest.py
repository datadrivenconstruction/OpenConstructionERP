# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_tax_withholding",
    version="1.0.0",
    display_name="Withholding Tax",
    description=(
        "Statutory construction withholding tax and VAT reverse charge. The "
        "payer deducts tax from a subcontractor and remits it to the state "
        "(UK CIS, German Bauabzugsteuer, Irish RCT, Italian ritenuta "
        "d'acconto, US backup withholding), and on a reverse-charge supply "
        "the buyer accounts for the VAT so the invoice must carry the "
        "statutory wording and no VAT amount."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    markets=["DE", "ES", "FR", "GB", "HU", "IE", "IT", "US"],
    auto_install=True,
    enabled=True,
)
