# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_leasing",
    version="0.1.0",
    display_name="Leasing",
    description=(
        "Leases of units to tenants in any country: terms, deposit, escalation (fixed or index), "
        "rent schedule raised as finance invoices, rent roll, arrears read from finance payments, "
        "renewals, notices and terminations with an event trail, export with pluggable profiles"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_contacts", "oe_finance"],
    optional_depends=["oe_legal_entities", "oe_property_dev", "oe_assets", "oe_documents"],
    auto_install=True,
    enabled=True,
)
