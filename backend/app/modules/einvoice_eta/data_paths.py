# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the einvoice_eta module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (clears invoices, credit notes and debit notes with the Egyptian Tax Authority. Builds the ETA v1.0 JSON document from a finance invoice with the published calculation rules, checks it before it leaves, signs it with the company's eSeal through a pluggable signer (USB token or HSM over PKCS#11, or an external signing service) and talks to the ETA API. A plugin of the e-invoice clearance module: it adds no tables and registers an adapter, a document builder and validation rules into that module's registries); reads code of einvoice_clearance, finance",
)
