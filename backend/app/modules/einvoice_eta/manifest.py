# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egyptian Tax Authority e-invoicing adapter manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_einvoice_eta",
    version="1.0.0",
    display_name="Egypt ETA e-invoicing",
    description=(
        "Clears invoices, credit notes and debit notes with the Egyptian Tax "
        "Authority. Builds the ETA v1.0 JSON document from a finance invoice "
        "with the published calculation rules, checks it before it leaves, "
        "signs it with the company's eSeal through a pluggable signer (USB "
        "token or HSM over PKCS#11, or an external signing service) and talks "
        "to the ETA API. A plugin of the e-invoice clearance module: it adds no "
        "tables and registers an adapter, a document builder and validation "
        "rules into that module's registries."
    ),
    author="OpenConstructionERP Core Team",
    category="integration",
    depends=["oe_einvoice_clearance"],
    auto_install=True,
    enabled=True,
)
