# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi facts the package reads, each with its source and the date it takes effect.

Three tables:

* ``VAT_RATES``: the standard VAT rate by period. The builder takes the rate for
  a document from here by its supply date, never from a constant, because
  invoices dated before 2020-07-01 carry 5%.
* ``CONSTRUCTION_RULES``: the VAT treatment of the construction events the
  ZATCA contracting-sector guideline (second issue, May 2026) addresses, with
  the paragraph each is read from.
* ``ENVIRONMENTS``: the Fatoora gateways and the API paths.

A row marked ``needs_expert_review`` is shipped as data, never enforced as a
hard rule, because the research behind it is secondary or unconfirmed.

``SA_VAT_TEMPLATE`` gives the dangling ``sa_vat_15`` template name of the Saudi
partner pack a meaning: it is the ``SA``/``VAT`` row of the dated tax seed
(``i18n_foundation/seed_data/tax_configurations.json``), the standard rate in
force on the document's date. No pack template resolves anywhere in the
platform today (the pack applier records the name "for reference"); a resolver
for every pack is a platform decision this package does not take.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

VAT_GUIDE_URL = "https://zatca.gov.sa/en/RulesRegulations/Taxes/Pages/default.aspx"
CONTRACTING_GUIDELINE_URL = "https://zatca.gov.sa/en/HelpCenter/guidelines/Documents/Guideline-For-the-Contracting-Sector-under-VAT-Provision.pdf"
DEVELOPER_PORTAL_CONFIG_URL = "https://sandbox.zatca.gov.sa/env-config.js"
DEVELOPER_PORTAL_URL = "https://sandbox.zatca.gov.sa/IntegrationSandbox"


@dataclass(frozen=True)
class VatRate:
    rate: Decimal
    valid_from: dt.date
    valid_to: dt.date | None
    source_url: str
    legal_basis: str


VAT_RATES: tuple[VatRate, ...] = (
    VatRate(
        rate=Decimal("5"),
        valid_from=dt.date(2018, 1, 1),
        valid_to=dt.date(2020, 6, 30),
        source_url=VAT_GUIDE_URL,
        legal_basis="VAT Law (Royal Decree M/113 of 1438H), Art. 2",
    ),
    VatRate(
        rate=Decimal("15"),
        valid_from=dt.date(2020, 7, 1),
        valid_to=None,
        source_url=VAT_GUIDE_URL,
        # The instrument's number is not verified against a primary text here.
        legal_basis="VAT Law Art. 2 as amended with effect from 2020-07-01 (Royal Order of May 2020)",
    ),
)

# The pack's template name and the seed row it stands for.
SA_VAT_TEMPLATE = "sa_vat_15"
SA_VAT_TEMPLATE_SEED = {"country_code": "SA", "tax_code": "VAT"}


def standard_rate_on(day: dt.date) -> Decimal | None:
    """The standard VAT rate in force on ``day``, or ``None`` before VAT existed."""
    for row in VAT_RATES:
        if row.valid_from <= day and (row.valid_to is None or day <= row.valid_to):
            return row.rate
    return None


# ── Construction VAT (P4, contracting-sector guideline, second issue May 2026) ──

KIND_INTERIM = "interim"
KIND_FINAL = "final"
KIND_ADVANCE = "advance"
KIND_RETENTION_RELEASE = "retention_release"
KIND_LIQUIDATED_DAMAGES = "liquidated_damages"
KIND_DAMAGES_COMPENSATION = "damages_compensation"
KIND_SECURITY_DEPOSIT = "security_deposit"
KIND_VARIATION = "variation"
CONSTRUCTION_KINDS: tuple[str, ...] = (
    KIND_INTERIM,
    KIND_FINAL,
    KIND_ADVANCE,
    KIND_RETENTION_RELEASE,
    KIND_LIQUIDATED_DAMAGES,
    KIND_DAMAGES_COMPENSATION,
    KIND_SECURITY_DEPOSIT,
    KIND_VARIATION,
)


@dataclass(frozen=True)
class ConstructionRule:
    """How one construction event is invoiced under Saudi VAT."""

    kind: str
    # The document types the event is issued as; empty means no tax document.
    document_types: tuple[str, ...]
    treatment: str
    section: str
    effective_from: dt.date
    source_url: str = CONTRACTING_GUIDELINE_URL
    needs_expert_review: bool = False


CONSTRUCTION_RULES: dict[str, ConstructionRule] = {
    r.kind: r
    for r in (
        ConstructionRule(
            kind=KIND_INTERIM,
            document_types=("388",),
            treatment=(
                "VAT is due on the full amount invoiced, retention included. Construction is a continuous supply, "
                "so the invoice fixes the date of supply."
            ),
            section="§5.2, Example 4; §4.1",
            effective_from=dt.date(2018, 1, 1),
        ),
        ConstructionRule(
            kind=KIND_FINAL,
            document_types=("388",),
            treatment=(
                "A tax invoice for the remaining value. Advances already invoiced are deducted as prepayment lines "
                "(KSA-26 to KSA-34) with the prepaid amount."
            ),
            section="§5.3; XML Implementation Standard §9.5",
            effective_from=dt.date(2018, 1, 1),
        ),
        ConstructionRule(
            kind=KIND_ADVANCE,
            document_types=("386",),
            treatment="A down payment is taxed on receipt: a tax invoice (prepayment, 386) for the amount received.",
            section="§5.3, Example 5",
            effective_from=dt.date(2018, 1, 1),
        ),
        ConstructionRule(
            kind=KIND_RETENTION_RELEASE,
            document_types=(),
            treatment=(
                "No invoice and no VAT when the customer pays retention back: the VAT was due on the invoice that "
                "billed the full amount."
            ),
            section="§5.2, Example 4",
            effective_from=dt.date(2018, 1, 1),
        ),
        ConstructionRule(
            kind=KIND_LIQUIDATED_DAMAGES,
            document_types=("381",),
            treatment=(
                "Contractual liquidated damages reduce the consideration: a credit note including VAT against the "
                "invoice they reduce."
            ),
            section="§5.4, Example 6",
            effective_from=dt.date(2018, 1, 1),
        ),
        ConstructionRule(
            kind=KIND_DAMAGES_COMPENSATION,
            document_types=(),
            treatment=(
                "Actual damages to the customer's property, or compensation awarded by a court or another "
                "independent body, are not an adjustment of the contract price: no credit note."
            ),
            section="§5.4, Example 7",
            effective_from=dt.date(2018, 1, 1),
        ),
        ConstructionRule(
            kind=KIND_SECURITY_DEPOSIT,
            document_types=(),
            treatment=(
                "A deposit held with a third party or in a separate account that the supplier cannot use is out of "
                "scope until it becomes available to the supplier; then VAT is due on it."
            ),
            section="§5.3, Example 5",
            effective_from=dt.date(2018, 1, 1),
        ),
        ConstructionRule(
            kind=KIND_VARIATION,
            document_types=("383", "388"),
            treatment="An increase of the agreed price is a debit note against the invoice, or a further tax invoice.",
            section="§5.1",
            effective_from=dt.date(2018, 1, 1),
            needs_expert_review=True,
        ),
    )
}


@dataclass(frozen=True)
class GovernmentTaxPoint:
    """VAT IR Art 20(5) as amended: the tax point of a government contract claim."""

    treatment: str = (
        "For a supply to a government entity under a contract concluded under the Government Tenders and "
        "Procurement Law, tax is due on the date the payment order for the claim is issued, or on receipt of the "
        "consideration if earlier. It applies to claims submitted from 2021-11-01, and only to the main contractor "
        "contracted directly with the entity, not to subcontractors."
    )
    section: str = "§4.2; VAT Implementing Regulations Art. 20 (amended); ZATCA Board decision 06-02-21 of 2021-10-03"
    claims_from: dt.date = dt.date(2021, 11, 1)
    source_url: str = CONTRACTING_GUIDELINE_URL
    # BR-KSA-91 / 92 (SDK 238 schematron): the buyer's legal form is "GOV" and
    # the tax point date (BT-7) is the payment order date.
    xml_rule: str = "BR-KSA-91, BR-KSA-92"


GOVERNMENT_TAX_POINT = GovernmentTaxPoint()

# Simplified invoices are reported within 24 hours of issue (Detailed Guidelines §6.4).
REPORTING_DEADLINE = dt.timedelta(hours=24)


# ── Fatoora environments ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Environment:
    key: str
    label: str
    base_url: str
    live: bool


GATEWAY = "https://gw-fatoora.zatca.gov.sa/e-invoicing"
ENVIRONMENTS: dict[str, Environment] = {
    e.key: e
    for e in (
        Environment("developer_portal", "Developer portal (sandbox)", f"{GATEWAY}/developer-portal", live=False),
        Environment("simulation", "Simulation", f"{GATEWAY}/simulation", live=False),
        Environment("production", "Production", f"{GATEWAY}/core", live=True),
    )
}


@dataclass(frozen=True)
class ApiPath:
    path: str
    method: str
    source: str
    needs_expert_review: bool


# Reporting is confirmed by the developer portal's own help text; the others
# are the paths every published integration uses and are not yet exercised here.
API_PATHS: dict[str, ApiPath] = {
    "compliance_csid": ApiPath("/compliance", "POST", DEVELOPER_PORTAL_URL, needs_expert_review=True),
    "compliance_invoice": ApiPath("/compliance/invoices", "POST", DEVELOPER_PORTAL_URL, needs_expert_review=True),
    "production_csid": ApiPath("/production/csids", "POST", DEVELOPER_PORTAL_URL, needs_expert_review=True),
    "production_csid_renewal": ApiPath("/production/csids", "PATCH", DEVELOPER_PORTAL_URL, needs_expert_review=True),
    "reporting": ApiPath("/invoices/reporting/single", "POST", DEVELOPER_PORTAL_URL, needs_expert_review=False),
    "clearance": ApiPath("/invoices/clearance/single", "POST", DEVELOPER_PORTAL_URL, needs_expert_review=True),
}

# Not stored as numbers on purpose; the API's answer decides (research: UNCONFIRMED).
UNCONFIRMED_FACTS: tuple[str, ...] = (
    "OTP lifetime (about one hour)",
    "Compliance CSID validity (about 24 hours)",
    "Whether wave 25 is the last integration wave",
    "The e-invoicing penalty schedule",
)

__all__ = [
    "API_PATHS",
    "CONSTRUCTION_KINDS",
    "CONSTRUCTION_RULES",
    "ENVIRONMENTS",
    "GOVERNMENT_TAX_POINT",
    "KIND_ADVANCE",
    "KIND_DAMAGES_COMPENSATION",
    "KIND_FINAL",
    "KIND_INTERIM",
    "KIND_LIQUIDATED_DAMAGES",
    "KIND_RETENTION_RELEASE",
    "KIND_SECURITY_DEPOSIT",
    "KIND_VARIATION",
    "REPORTING_DEADLINE",
    "SA_VAT_TEMPLATE",
    "SA_VAT_TEMPLATE_SEED",
    "UNCONFIRMED_FACTS",
    "VAT_RATES",
    "ApiPath",
    "ConstructionRule",
    "Environment",
    "GovernmentTaxPoint",
    "VatRate",
    "standard_rate_on",
]
