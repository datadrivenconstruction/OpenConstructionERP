# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International electronic-invoicing module.

Outbound EN 16931 invoice writer in both syntaxes:
    * CII  - ZUGFeRD 2.1, Factur-X 1.0, XRechnung 3.0 (DACH/EU)
    * UBL  - Peppol BIS Billing 3.0 and plain EN 16931 UBL (worldwide)

One EN 16931 model, many country profiles (see ``profiles.py``); adding a
country is one registry entry. The core is an ORM-free library: it takes
plain dicts and returns XML or PDF bytes, with no database dependency.

Two API surfaces expose it:
    * The finance module renders a persisted ``Invoice`` aggregate through
      ``/invoices/{id}/einvoice`` and manages the standing e-invoice settings.
    * This module's own ``router.py`` exposes standalone validation and
      generation at ``/api/v1/einvoice/``, accepting raw dicts for
      integrations, pre-flight checks and testing.

The inbound counterpart is ``supplier_catalogs.peppol`` (UBL parser).
"""

from app.modules.einvoice.cii import (
    EInvoice,
    EInvoiceError,
    EInvoiceLine,
    Party,
    TaxSubtotal,
    build_cii_xml,
    profile_problems,
    validate,
    validate_semantics,
)
from app.modules.einvoice.profiles import (
    PROFILES,
    SUPPORTED_PROFILES,
    Profile,
    get_profile,
)
from app.modules.einvoice.rules import (
    DE_INVOICE_TYPE_CODES,
    DIRECT_DEBIT_CODES,
    FATAL,
    PAYMENT_CARD_CODES,
    UNTDID_4461_CODES,
    WARNING,
    RuleViolation,
)
from app.modules.einvoice.service import (
    build_einvoice,
    problems_for,
    render_einvoice,
    render_einvoice_pdf,
    violations_for,
)
from app.modules.einvoice.ubl import build_ubl_xml, is_credit_note

__all__ = [
    "DE_INVOICE_TYPE_CODES",
    "DIRECT_DEBIT_CODES",
    "FATAL",
    "PAYMENT_CARD_CODES",
    "PROFILES",
    "SUPPORTED_PROFILES",
    "UNTDID_4461_CODES",
    "WARNING",
    "EInvoice",
    "EInvoiceError",
    "EInvoiceLine",
    "Party",
    "Profile",
    "RuleViolation",
    "TaxSubtotal",
    "build_cii_xml",
    "build_einvoice",
    "build_ubl_xml",
    "get_profile",
    "is_credit_note",
    "problems_for",
    "profile_problems",
    "render_einvoice",
    "render_einvoice_pdf",
    "validate",
    "validate_semantics",
    "violations_for",
]
