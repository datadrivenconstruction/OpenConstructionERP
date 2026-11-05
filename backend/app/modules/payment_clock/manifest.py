# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment clock module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_payment_clock",
    version="1.0.0",
    display_name="Payment Clock",
    description=(
        "The statutory payment clock. In the United Kingdom, Ireland, "
        "Australia, New Zealand, Singapore and Malaysia the dates and notices "
        "around a payment application are set by statute rather than agreed; "
        "in Germany the VOB/B and the BGB fix the payment deadlines for "
        "interim and final invoices. Missing one has a defined legal "
        "consequence. This module holds the regime, computes the due date, "
        "the notice deadlines and the final date for payment, records the "
        "notices actually served, and reports the consequence when a deadline "
        "passes unanswered."
    ),
    author="OpenConstructionERP Core Team",
    # Regional rather than core: which regime applies is a question about where
    # the work is, and a deployment that never works in a security-of-payment
    # jurisdiction should be able to switch this off.
    category="regional",
    # ``oe_projects`` only. The clock points at a progress claim or a
    # subcontractor payment application by plain id, never by foreign key, so
    # neither of those modules has to be installed for this one to load.
    depends=["oe_projects"],
    optional_depends=["oe_contracts", "oe_subcontractors"],
    markets=[
        "AU",
        "BG",
        "CA",
        "CN",
        "DE",
        "EG",
        "ES",
        "EU",
        "FR",
        "GB",
        "HU",
        "IE",
        "IN",
        "MY",
        "NG",
        "NZ",
        "PE",
        "PK",
        "PL",
        "RU",
        "SA",
        "SG",
        "TR",
        "US",
        "ZA",
    ],
    auto_install=True,
    enabled=True,
)
