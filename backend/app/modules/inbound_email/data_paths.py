# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the inbound_email module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (imports project correspondence that arrives as a stored message file (an exported RFC-822 / .eml), normalizes it (subject, sender, recipients, threading ids, text body and attachment metadata) and scans it for construction delay signals, proposing a starter set of schedule activities for the forensic-delay workflow. File import only, not a live mailbox; nothing is persisted, so no migration)",
)
