# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inbound email module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.inbound_email.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_inbound_email",
    version="0.1.0",
    display_name="Inbound Email",
    description=(
        "Imports project correspondence that arrives as a stored message file "
        "(an exported RFC-822 / .eml), normalizes it (subject, sender, "
        "recipients, threading ids, text body and attachment metadata) and "
        "scans it for construction delay signals, proposing a starter set of "
        "schedule activities for the forensic-delay workflow. File import only, "
        "not a live mailbox; nothing is persisted, so no migration"
    ),
    author="OpenConstructionERP Core Team",
    category="controls",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
