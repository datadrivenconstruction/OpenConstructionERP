# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_einvoice",
    version="1.0.0",
    display_name="E-invoice",
    description=(
        "EN 16931 electronic invoice library with standalone validation and "
        "generation API. Supports CII (ZUGFeRD 2.1, Factur-X 1.0, XRechnung 3.0) "
        "and UBL (Peppol BIS Billing 3.0) syntaxes. The finance module uses this "
        "library to render persisted invoices; this module exposes the same "
        "capabilities as a standalone API for integrations and dry-run validation."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],  # pure library; finance depends on us, not the other way
    auto_install=True,
    enabled=True,
)
