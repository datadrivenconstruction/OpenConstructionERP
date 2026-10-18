# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_payment_release",
    version="1.0.0",
    display_name="Payment Release",
    description=(
        "Contract payment terms, payment release computation from the gross invoiced to the amount to pay, "
        "invoice ledger per contract and project, and the retention register with release postings"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_contracts", "oe_finance", "oe_costmodel"],
    auto_install=True,
    enabled=True,
)
