# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Polish KSeF e-invoicing adapter manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_einvoice_ksef",
    version="1.0.0",
    display_name="Poland KSeF e-invoicing",
    description=(
        "Issues invoices through KSeF, the Polish national e-invoicing system. Builds the FA(3) "
        "document from a finance invoice (basic, corrective, advance and settlement invoices, split "
        "payment and Annex 15 markers), produces the KOD I and KOD II verification QR codes, tracks "
        "the offline modes and their upload deadlines, and talks to the KSeF API 2.0. Checks that "
        "payment titles carry the KSeF number from 2027. A plugin of the e-invoice clearance module: "
        "it adds no tables and registers an adapter, a document builder and validation rules into "
        "that module's registries."
    ),
    author="OpenConstructionERP Core Team",
    category="integration",
    depends=["oe_einvoice_clearance"],
    auto_install=True,
    enabled=True,
)
