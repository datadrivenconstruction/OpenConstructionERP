# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the einvoice module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (eN 16931 electronic invoice library with standalone validation and generation API. Supports CII (ZUGFeRD 2.1, Factur-X 1.0, XRechnung 3.0) and UBL (Peppol BIS Billing 3.0) syntaxes. The finance module uses this library to render persisted invoices; this module exposes the same capabilities as a standalone API for integrations and dry-run validation)",
)
