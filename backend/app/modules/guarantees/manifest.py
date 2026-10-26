# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_guarantees",
    version="1.0.0",
    display_name="Guarantees and Bonds",
    description=(
        "Register of bank guarantees and bonds: bid bonds, performance bonds, advance payment and "
        "retention guarantees, warranty bonds and parent company guarantees, given to clients or "
        "received from subcontractors. Tracks issuer, beneficiary, amount, expiry, auto-extension and "
        "claim period through a status lifecycle with a full audit history, reduces the advance "
        "guarantee as interim payments recover the advance, gates the first payment on the "
        "performance bond, alerts 60, 30 and 14 days before expiry and shows company exposure by bank, "
        "by type and against bank credit lines."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects"],
    optional_depends=["oe_contracts", "oe_documents", "oe_notifications", "oe_subcontractors", "oe_tendering"],
    auto_install=True,
    enabled=True,
)
