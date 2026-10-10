# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shipped withholding schemes and reverse-charge rules.

Seed data, not a migration. A rate change or a new country is then an ordinary
code change that ships with a release, reviewable in a diff, instead of a
schema revision that can only run once; and an operator who has edited a rate
for their own reasons keeps that edit, because seeding only fills gaps.

Two catalogues, and they are different shapes on purpose:

* :data:`WITHHOLDING_REGIMES` becomes rows in ``oe_tax_withholding_regime``.
  A regime is a record with a life - parties are attached to it and deductions
  quote it - so it has to exist in the database.
* :data:`REVERSE_CHARGE_RULES` stays a lookup. A reverse charge is decided per
  invoice, and what the catalogue supplies is the statutory wording and the
  legal reference to copy onto that invoice. There is no reverse-charge
  *record* to keep between invoices, so there is no table for one.

``materials_excluded`` and ``vat_excluded`` are set per scheme and are not a
house style. They differ between countries and getting them wrong is the
expensive failure this module exists to prevent:

* The UK scheme deducts on labour only, so materials leave the base. Deducting
  on the gross over-withholds on every payment a subcontractor supplies
  materials on, and they only recover it at the end of their tax year.
* The German scheme is the opposite on both counts: section 48 EStG deducts
  from the *Gegenleistung*, which is the consideration including VAT, with no
  carve-out for materials.

Rates and thresholds are as published at the time of writing and are
deliberately data rather than code. Verify them against the authority before
relying on a figure for a filing.
"""

from __future__ import annotations

from typing import Any

# ── Withholding schemes ──────────────────────────────────────────────────────
#
# ``bands`` are ordered from the lowest rate to the highest. ``rate_pct`` is a
# percent as a string - it is read into a Decimal, never a float.
# ``requires_verification`` marks the bands an unverified party may not sit in,
# which is what the expired-verification rule enforces.

WITHHOLDING_REGIMES: tuple[dict[str, Any], ...] = (
    {
        "country_code": "GB",
        "scheme_code": "UK_CIS",
        "scheme_name": "Construction Industry Scheme",
        "legal_reference": "Finance Act 2004 Part 3 Chapter 3",
        "authority": "HM Revenue & Customs",
        "currency_code": "GBP",
        "default_band_code": "HIGHER",
        "materials_excluded": True,
        "vat_excluded": True,
        # A verification is good for the tax year it is made in and the two
        # following tax years, so three years is the working life.
        "verification_validity_months": 36,
        "threshold_amount": None,
        "bands": [
            {
                "code": "GROSS",
                "label": "Gross payment status",
                "rate_pct": "0",
                "requires_verification": True,
            },
            {
                "code": "STANDARD",
                "label": "Registered subcontractor",
                "rate_pct": "20",
                "requires_verification": True,
            },
            {
                "code": "HIGHER",
                "label": "Unverified or unmatched subcontractor",
                "rate_pct": "30",
                "requires_verification": False,
            },
        ],
        "notes": (
            "The deduction is taken on labour only: the cost of materials, plant hire and "
            "consumables the subcontractor supplies is removed from the base first. "
            "The band comes from verifying the subcontractor with the authority, and the "
            "verification reference is what evidences it."
        ),
    },
    {
        "country_code": "DE",
        "scheme_code": "DE_BAUABZUGSTEUER",
        "scheme_name": "Bauabzugsteuer",
        "legal_reference": "section 48 EStG",
        "authority": "Bundeszentralamt fuer Steuern",
        "currency_code": "EUR",
        "default_band_code": "STANDARD",
        # Section 48 EStG deducts from the Gegenleistung, which is the
        # consideration *including* VAT and with no materials carve-out. Both
        # flags are therefore False, and they are the reason both are columns.
        "materials_excluded": False,
        "vat_excluded": False,
        "verification_validity_months": 36,
        # Exemption limit per payee per calendar year. Below it no deduction is
        # made at all, which is a different thing from a zero rate.
        "threshold_amount": "5000.00",
        "bands": [
            {
                "code": "EXEMPT",
                "label": "Freistellungsbescheinigung held (section 48b EStG)",
                "rate_pct": "0",
                "requires_verification": True,
            },
            {
                "code": "STANDARD",
                "label": "No exemption certificate held",
                "rate_pct": "15",
                "requires_verification": False,
            },
        ],
        "notes": (
            "Fifteen percent of the consideration unless the payee holds a valid "
            "Freistellungsbescheinigung under section 48b EStG. The certificate carries its "
            "own end date, and the exemption ends with it whether or not anyone notices."
        ),
    },
    {
        "country_code": "IE",
        "scheme_code": "IE_RCT",
        "scheme_name": "Relevant Contracts Tax",
        "legal_reference": "Taxes Consolidation Act 1997 Part 18 Chapter 2",
        "authority": "Revenue Commissioners",
        "currency_code": "EUR",
        "default_band_code": "HIGHER",
        # RCT applies to the payment under the relevant contract, materials
        # included; VAT is outside it (construction services between accountable
        # persons are reverse charged, so there is usually no VAT to remove).
        "materials_excluded": False,
        "vat_excluded": True,
        "verification_validity_months": 0,
        "threshold_amount": None,
        "bands": [
            {"code": "ZERO", "label": "Zero rate", "rate_pct": "0", "requires_verification": True},
            {"code": "STANDARD", "label": "Standard rate", "rate_pct": "20", "requires_verification": True},
            {
                "code": "HIGHER",
                "label": "Higher rate (unknown or non-compliant subcontractor)",
                "rate_pct": "35",
                "requires_verification": False,
            },
        ],
        "notes": (
            "The rate is set by the authority per subcontractor and notified to the principal "
            "contractor; it is not chosen. A deduction authorisation is obtained for each "
            "payment before it is made."
        ),
    },
    {
        "country_code": "IT",
        "scheme_code": "IT_RITENUTA_APPALTI",
        "scheme_name": "Ritenuta d'acconto sui corrispettivi per contratti di appalto",
        "legal_reference": "art. 25-ter DPR 600/1973",
        "authority": "Agenzia delle Entrate",
        "currency_code": "EUR",
        "default_band_code": "STANDARD",
        "materials_excluded": False,
        "vat_excluded": True,
        "verification_validity_months": 0,
        "threshold_amount": None,
        "bands": [
            {
                "code": "STANDARD",
                "label": "Ritenuta d'acconto on works and maintenance contracts",
                "rate_pct": "4",
                "requires_verification": False,
            },
        ],
        "notes": (
            "Four percent withheld on account from the consideration, net of VAT, for works "
            "and maintenance contracts. The payer certifies the withholding to the payee, who "
            "sets it against their own liability."
        ),
    },
    {
        "country_code": "US",
        "scheme_code": "US_BACKUP_WITHHOLDING",
        "scheme_name": "Backup withholding",
        "legal_reference": "Internal Revenue Code section 3406",
        "authority": "Internal Revenue Service",
        "currency_code": "USD",
        "default_band_code": "BACKUP",
        "materials_excluded": False,
        # There is no VAT in the United States; sales and use tax is charged and
        # remitted separately and is not part of this base.
        "vat_excluded": False,
        "verification_validity_months": 0,
        "threshold_amount": None,
        "bands": [
            {
                "code": "NONE",
                "label": "Taxpayer identification number certified",
                "rate_pct": "0",
                "requires_verification": True,
            },
            {
                "code": "BACKUP",
                "label": "No certified taxpayer identification number on file",
                "rate_pct": "24",
                "requires_verification": False,
            },
        ],
        "notes": (
            "Applies when the payee has not provided a certified taxpayer identification "
            "number, or the authority has notified the payer to withhold. The evidence is the "
            "signed request-for-taxpayer-identification form on file."
        ),
    },
    {
        # Gelir Vergisi Kanunu 193 art. 94 first paragraph item 3 and Kurumlar
        # Vergisi Kanunu 5520 art. 15(1)(a), read on mevzuat.gov.tr 2026-10-10:
        # "42 nci madde kapsamına giren işler dolayısıyla bu işleri yapanlara
        # (kurumlar dahil) ödenen istihkak bedellerinden". The rates are set by
        # Bakanlar Kurulu Kararı 2009/14592 as amended by Cumhurbaşkanı Kararı
        # 9707 (Resmî Gazete 30.3.2025 no. 32857, from 1.4.2025). That
        # decision's title is confirmed on the Resmî Gazete index but its body is
        # a scanned image, so the two figures and the net-of-KDV base were read
        # from secondary summaries. Pending review by a Turkish quantity surveyor.
        "country_code": "TR",
        "scheme_code": "TR_YILLARA_YAYGIN_INSAAT_STOPAJ",
        "scheme_name": "Yıllara yaygın inşaat ve onarım işleri hakediş stopajı",
        "legal_reference": "GVK 193 art. 94/3, KVK 5520 art. 15(1)(a), BKK 2009/14592 as amended by CBK 9707",
        "authority": "Gelir İdaresi Başkanlığı",
        "currency_code": "TRY",
        "default_band_code": "STANDARD",
        "materials_excluded": False,
        "vat_excluded": True,
        "verification_validity_months": 0,
        "threshold_amount": None,
        "bands": [
            {
                "code": "RAIL_AND_SHIP",
                "label": "Railway, tram, metro, funicular, monorail and ship construction or repair",
                "rate_pct": "1",
                "requires_verification": False,
            },
            {
                "code": "STANDARD",
                "label": "Other construction and repair works spanning more than one calendar year",
                "rate_pct": "5",
                "requires_verification": False,
            },
        ],
        "notes": (
            "Withheld by the payer from each progress payment (hakediş) on construction or repair "
            "works that run over more than one calendar year, and declared on the payer's monthly "
            "withholding return. The base is the hakediş amount before KDV. Works finished within one "
            "calendar year are outside the scheme. The band follows the kind of work, not a check on "
            "the contractor: the one percent band covers railway, tram, metro, funicular, monorail "
            "and ship construction and repair from 1 April 2025, and everything else is five percent."
        ),
    },
)


# ── Reverse charge ───────────────────────────────────────────────────────────
#
# On a reverse-charge supply the buyer accounts for the VAT instead of the
# seller. Two consequences, and both are checked by the validation rules: the
# invoice must carry the statutory wording, and it must not carry a VAT amount.
# The wording below is the sentence that goes on the document; it is data in
# the language the tax authority reads it in.

REVERSE_CHARGE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_code": "GB_DRC_CONSTRUCTION",
        "country_code": "GB",
        "name": "VAT domestic reverse charge for building and construction services",
        "legal_reference": "VAT Act 1994 section 55A",
        "invoice_wording": "Reverse charge: VAT Act 1994 Section 55A applies. Customer to pay the VAT to HMRC.",
        "notes": (
            "Applies between VAT-registered businesses on specified construction services "
            "reported under the Construction Industry Scheme, and stops at the end user, who "
            "must say in writing that they are one."
        ),
    },
    {
        "rule_code": "DE_13B_USTG",
        "country_code": "DE",
        "name": "Steuerschuldnerschaft des Leistungsempfaengers",
        "legal_reference": "section 13b UStG",
        "invoice_wording": "Steuerschuldnerschaft des Leistungsempfaengers (Paragraph 13b UStG).",
        "notes": (
            "Applies where the recipient of a construction service themselves supply "
            "construction services on a sustained basis. Independent of the section 48 EStG "
            "withholding: one moves the VAT, the other withholds income tax."
        ),
    },
    {
        "rule_code": "ES_ISP_CONSTRUCTION",
        "country_code": "ES",
        "name": "Inversion del sujeto pasivo",
        "legal_reference": "art. 84.Uno.2 f) Ley 37/1992",
        "invoice_wording": "Inversion del sujeto pasivo (art. 84.Uno.2 f) Ley 37/1992).",
        "notes": (
            "Applies to works of construction or refurbishment of buildings carried out under "
            "a contract between the developer and the main contractor, and down the chain of "
            "subcontracts under it."
        ),
    },
    {
        "rule_code": "FR_AUTOLIQUIDATION_BTP",
        "country_code": "FR",
        "name": "Autoliquidation de la TVA dans le batiment",
        "legal_reference": "art. 283-2 nonies CGI",
        "invoice_wording": "Autoliquidation - article 283-2 nonies du CGI. TVA due par le preneur.",
        "notes": (
            "Applies to construction works subcontracted by a taxable person established in "
            "France. The subcontractor invoices without VAT and the main contractor declares it."
        ),
    },
    {
        # Revenue: from 1 September 2008 a subcontractor does not charge VAT to
        # the principal contractor on construction services within Relevant
        # Contracts Tax; the principal accounts for it, and the invoice carries
        # this sentence and no VAT rate or amount. Revenue Tax and Duty Manual
        # "Reverse charge - construction", read 2026-10-04.
        "rule_code": "IE_RCT_REVERSE_CHARGE",
        "country_code": "IE",
        "name": "VAT reverse charge on construction services within Relevant Contracts Tax",
        "legal_reference": "section 16(3) VAT Consolidation Act 2010",
        "invoice_wording": "VAT on this supply to be accounted for by the Principal Contractor.",
        "notes": (
            "Applies where a subcontractor supplies construction services to a principal "
            "contractor and Relevant Contracts Tax applies to the contract, haulage excepted. "
            "The invoice shows the subcontractor's VAT number and no VAT rate or VAT amount."
        ),
    },
    {
        # Hungarian VAT Act (2007. evi CXXVII. torveny) section 142 (1) b) puts
        # the tax on the recipient of construction-assembly work on real
        # property that needs a building permit, an acknowledgement procedure
        # or a notification, and section 169 n) requires the words "forditott
        # adozas" on the invoice. NAV adozasi kerdes 20264, read 2026-10-04.
        "rule_code": "HU_FORDITOTT_ADOZAS_EPITES",
        "country_code": "HU",
        "name": "Fordított adózás építési-szerelési munkáknál",
        "legal_reference": "Áfa tv. 142. § (1) b), 169. § n)",
        "invoice_wording": "Fordított adózás",
        "notes": (
            "Applies between taxable persons registered for VAT in Hungary to construction and "
            "assembly work that creates, extends, converts or demolishes real property where that "
            "work needs a building permit, an acknowledgement procedure or a notification, which "
            "the customer confirms to the contractor in writing beforehand."
        ),
    },
)


def regime_by_scheme(scheme_code: str) -> dict[str, Any] | None:
    """The shipped definition of one scheme, or ``None`` when it is not shipped."""
    for regime in WITHHOLDING_REGIMES:
        if regime["scheme_code"] == scheme_code:
            return regime
    return None


def reverse_charge_rule(rule_code: str) -> dict[str, Any] | None:
    """The shipped reverse-charge rule, or ``None`` when the code is unknown."""
    for rule in REVERSE_CHARGE_RULES:
        if rule["rule_code"] == rule_code:
            return rule
    return None


__all__ = [
    "REVERSE_CHARGE_RULES",
    "WITHHOLDING_REGIMES",
    "regime_by_scheme",
    "reverse_charge_rule",
]
