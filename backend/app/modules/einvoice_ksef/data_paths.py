# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the einvoice_ksef module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (issues invoices through KSeF, the Polish national e-invoicing system. Builds the FA(3) document from a finance invoice (basic, corrective, advance and settlement invoices, split payment and Annex 15 markers), produces the KOD I and KOD II verification QR codes, tracks the offline modes and their upload deadlines, and talks to the KSeF API 2.0. Checks that payment titles carry the KSeF number from 2027. A plugin of the e-invoice clearance module: it adds no tables and registers an adapter, a document builder and validation rules into that module's registries); reads code of einvoice_clearance, finance",
)
