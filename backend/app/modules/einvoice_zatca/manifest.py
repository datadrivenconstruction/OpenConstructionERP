# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi ZATCA FATOORA e-invoicing manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_einvoice_zatca",
    version="1.0.0",
    display_name="Saudi Arabia ZATCA e-invoicing",
    description=(
        "Issues invoices through ZATCA FATOORA phase 2. Builds the UBL 2.1 KSA document from a finance "
        "invoice (tax invoice, credit and debit notes, advance invoices), keeps the invoice counter and "
        "previous-invoice-hash chain per EGS unit, applies the cryptographic stamp and the QR, onboards the "
        "unit with ZATCA (compliance and production CSID), and clears standard invoices and reports "
        "simplified ones. Checks the contracting-sector VAT treatment of retention, advances and damages. "
        "A plugin of the e-invoice clearance module: it registers an adapter, a document builder and "
        "validation rules into that module's registries."
    ),
    author="OpenConstructionERP Core Team",
    category="integration",
    depends=["oe_einvoice_clearance"],
    auto_install=True,
    enabled=True,
)
