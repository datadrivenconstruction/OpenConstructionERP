# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice clearance module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.einvoice_clearance.regimes import SUPPORTED_COUNTRIES

manifest = ModuleManifest(
    name="oe_einvoice_clearance",
    version="1.0.0",
    display_name="E-invoice clearance",
    description=(
        "Government clearance for electronic invoices. In a growing list of "
        "countries a PDF is not a legal invoice: Mexico, Brazil, Italy, Poland, "
        "Romania, Saudi Arabia and India clear the document with the tax "
        "authority before or as it is issued, Spain and Hungary report it "
        "afterwards, and the European public sector exchanges it over a "
        "network. This module holds the registration per country, the state of "
        "each document, the identifier the authority returned and the trail "
        "behind it. The document itself is built by the EN 16931 engine; the "
        "platforms are adapters behind an interface."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_finance", "oe_projects"],
    # Only markets whose pack ships an e-invoice mandate file see the module.
    markets=list(SUPPORTED_COUNTRIES),
    auto_install=True,
    enabled=True,
)
