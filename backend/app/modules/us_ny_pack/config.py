# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for the State of New York.

Same ownership split as the California and Texas packs: the national layer in
``app.modules.us_pack.config`` owns everything federal or nationwide, and this
module carries only what changes when the job is in New York. ``vat_rates`` is
empty for the same reason it is in ``us_pack``.

The rule that costs money in New York is the line between a capital improvement
and a repair. A capital improvement, documented by the customer's certificate,
is not taxed to the customer: the contractor pays tax on its materials and gets
no credit. A repair or maintenance job is taxed on the whole charge, labor
included. The same scope of work can be either, and the bid changes by the
combined rate times the whole price.

Every rule carries a ``statute_reference`` and an ``effective_date`` in the
convention the other state packs use (``None`` = long-standing, commencement not
established). No local rate is carried: the combined rate is a property of the
jobsite and the quarter, and the tax department publishes the lookup.
"""

from typing import Any

from app.modules.us_pack.statutory import US_CLAIMANT_ROLES, US_SECTORS, VERIFY_NOTE, common_bindings

# Publication 718 lists "New York State only" at 4 percent; every county and
# city stacks its own rate on top, so 4 is the floor and never the answer.
NY_STATE_SALES_TAX_PCT = "4"

NY_PRIVATE_RETAINAGE_CAP_PCT = "5"
NY_PRIVATE_RETAINAGE_MIN_CONTRACT_USD = "150000"
NY_224A_PROJECT_THRESHOLD_USD = "5000000"
NY_224A_PUBLIC_FUNDS_SHARE_PCT = "30"

_CAPITAL_IMPROVEMENTS_URL = "https://tax.ny.gov/pubs_and_bulls/tg_bulletins/st/capital_improvements.htm"
_LIEN_LAW_10_URL = "https://www.nysenate.gov/legislation/laws/LIE/10"

STATE_RULES: dict[str, list[dict[str, Any]]] = {
    # ── Sales and use tax ────────────────────────────────────────────────────
    "sales_tax": [
        {
            "code": "ny_state_rate",
            "name": "State sales and use tax rate",
            "description": (
                "The state rate is 4 percent. Counties, cities and school districts add their own rate on top, "
                "and the combined rate is a property of the jobsite address. New York City's combined rate is "
                "one of the highest in the state. Resolve the rate per address from the tax department's lookup."
            ),
            "value": NY_STATE_SALES_TAX_PCT,
            "unit": "percent",
            "statute_reference": "New York Tax Law §§ 1105 and 1210; Publication 718",
            "effective_date": None,
        },
        {
            "code": "ny_capital_improvement",
            "name": "Capital improvement: the customer is not taxed",
            "description": (
                "Work that is a capital improvement to real property is not a taxable service. The customer "
                "gives the contractor a certificate of capital improvement and the contractor charges no tax. The "
                "contractor is the consumer of the materials it incorporates and pays tax on them when it buys "
                "them, with no credit or refund. A capital improvement priced tax-free without the certificate on "
                "file leaves the contractor liable for the tax it did not collect."
            ),
            "value": None,
            "unit": None,
            "exemption_certificate": "ST-124",
            "statute_reference": "New York Tax Law §§ 1101(b)(9) and 1105(c)(3); Form ST-124",
            "source_url": _CAPITAL_IMPROVEMENTS_URL,
            "effective_date": None,
        },
        {
            "code": "ny_repair_maintenance",
            "name": "Repair, maintenance and installation: the whole charge is taxed",
            "description": (
                "Repairing, maintaining or servicing real property, and installing property that does not become "
                "a capital improvement, is a taxable service. Tax is charged on the full bill, materials and "
                "labor together, at the combined rate of the place the service is delivered."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "New York Tax Law § 1105(c)(3) and (5)",
            "source_url": _CAPITAL_IMPROVEMENTS_URL,
            "effective_date": None,
        },
    ],
    # ── Prevailing wage ──────────────────────────────────────────────────────
    "prevailing_wage": [
        {
            "code": "ny_prevailing_wage_article_8",
            "name": "Public work pays the prevailing rate",
            "description": (
                "Laborers, workers and mechanics on a public work contract must be paid the prevailing rate of "
                "wages and supplements. Outside New York City the schedule comes from the state labor department, "
                "which publishes it each year on 1 July; inside the city the Comptroller publishes it. A public "
                "work with no schedule from the right authority has no rate anyone can check payroll against."
            ),
            "value": None,
            "unit": None,
            "rate_setting_authority": "state_labor_department_or_nyc_comptroller",
            "statute_reference": "New York Labor Law Article 8, § 220",
            "source_url": "https://dol.ny.gov/overview-prevailing-wage-and-bureau-public-work",
            "effective_date": None,
        },
        {
            "code": "ny_electronic_certified_payroll",
            "name": "Certified payroll is filed electronically",
            "description": (
                "Contractors and subcontractors on Article 8 public work submit certified payroll electronically "
                "to the state labor department, in the department's XML format or through its portal. The platform "
                "exports the file; a person files it."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "New York Labor Law § 220; state labor department electronic payroll requirement",
            "source_url": "https://dol.ny.gov/Electronic-Payroll",
            "effective_date": "2025-12-31",
        },
        {
            "code": "ny_covered_private_project_224a",
            "name": "Private projects paid for in part with public funds",
            "description": (
                "A private construction project costing more than 5 million dollars and paid for at least 30 "
                "percent with public funds is a covered project and carries prevailing wage, for contracts entered "
                "into on or after 1 January 2022. The share and the total are tested together."
            ),
            "value": NY_224A_PROJECT_THRESHOLD_USD,
            "unit": "usd",
            "public_funds_share_percent": NY_224A_PUBLIC_FUNDS_SHARE_PCT,
            "statute_reference": "New York Labor Law § 224-a",
            "source_url": "https://newyork.public.law/laws/n.y._labor_law_section_224-a",
            "effective_date": "2022-01-01",
        },
    ],
    # ── Retainage ────────────────────────────────────────────────────────────
    "retainage": [
        {
            "code": "ny_private_retainage_cap",
            "name": "Private retainage capped at 5 percent",
            "description": (
                "On a private construction contract of at least 150 thousand dollars entered into on or after 17 "
                "November 2023, retainage may not exceed 5 percent of each progress payment, all the way down the "
                "chain. The value threshold is the contract's, not the payment's."
            ),
            "value": NY_PRIVATE_RETAINAGE_CAP_PCT,
            "unit": "percent",
            "works": "private",
            "applies_when_contract_value_usd_at_or_above": NY_PRIVATE_RETAINAGE_MIN_CONTRACT_USD,
            "statute_reference": "New York General Business Law §§ 756 and 756-c",
            "source_url": "https://law.justia.com/codes/new-york/gbs/article-35-e/756/",
            "effective_date": "2023-11-17",
        },
        {
            "code": "ny_private_retainage_clause_void",
            "name": "A clause above the cap is void",
            "description": (
                "A contract term that provides for retainage above the statutory cap is void and unenforceable "
                "as against public policy. The contract still stands; the excess retainage does not."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "New York General Business Law § 757",
            "source_url": "https://www.nysenate.gov/legislation/laws/GBS/757",
            "effective_date": "2025-12-19",
        },
        {
            "code": "ny_public_retainage",
            "name": "Public retainage 5 percent",
            "description": (
                "State agencies and local public owners hold no more than 5 percent of each progress payment, and "
                "pay within 30 days on their own payment clocks."
            ),
            "value": "5",
            "unit": "percent",
            "statute_reference": "New York State Finance Law § 139-f; General Municipal Law § 106-b",
            "effective_date": None,
        },
    ],
    # ── Prompt payment ───────────────────────────────────────────────────────
    "prompt_payment": [
        {
            "code": "ny_public_state_payment",
            "name": "State agency pays in 30 days",
            "description": "The state's prompt payment clock, seeded as a payment clock regime.",
            "value": "30",
            "unit": "days",
            "payment_clock_regime": "us_ny_public_state_179f",
            "statute_reference": "New York State Finance Law § 179-f",
            "effective_date": None,
        },
        {
            "code": "ny_public_local_payment",
            "name": "Local public owner pays in 30 days",
            "description": "The local public owner's clock, seeded as a payment clock regime.",
            "value": "30",
            "unit": "days",
            "payment_clock_regime": "us_ny_public_local_106b",
            "statute_reference": "New York General Municipal Law § 106-b",
            "effective_date": None,
        },
        {
            "code": "ny_private_payment",
            "name": "Private owner pays in 30 days of approval",
            "description": (
                "On a covered private contract the owner pays an approved invoice within 30 days of approving "
                "it, and a late payment carries interest at 12 percent a year."
            ),
            "value": "30",
            "unit": "days",
            "payment_clock_regime": "us_ny_private_756a",
            "statute_reference": "New York General Business Law §§ 756-a and 756-b",
            "effective_date": "2023-11-17",
        },
    ],
    # ── Mechanic's lien ──────────────────────────────────────────────────────
    "lien": [
        {
            "code": "ny_lien_filing",
            "name": "File the notice of lien within 8 months",
            "description": (
                "A notice of lien may be filed at any time during the work and within 8 months after the "
                "completion of the contract or the final performance of the work or the final furnishing of "
                "materials, whichever is later."
            ),
            "value": "8",
            "unit": "months",
            "statute_reference": "New York Lien Law § 10",
            "source_url": _LIEN_LAW_10_URL,
            "effective_date": None,
        },
        {
            "code": "ny_lien_filing_single_family",
            "name": "Single family dwelling: 4 months",
            "description": (
                "For an improvement to a single family dwelling the window is 4 months, and courts have applied "
                "the single family period to an individual condominium or cooperative unit."
            ),
            "value": "4",
            "unit": "months",
            "statute_reference": "New York Lien Law § 10",
            "source_url": _LIEN_LAW_10_URL,
            "effective_date": None,
        },
    ],
}

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "US_NY",
    "subdivision_code": "US-NY",
    "subdivision_name": "New York",
    "countries": ["US"],
    "parent_pack": "oe_us_pack",
    "default_currency": "USD",
    "default_locale": "en-US",
    "measurement_system": "imperial",
    "paper_size": "Letter",
    "date_format": "MM/DD/YYYY",
    "number_format": "1,234.56",
    # ── Licensing ────────────────────────────────────────────────────────────
    "contractor_licensing": {
        "state_general_contractor_licence": False,
        "note": (
            "New York does not license general contractors at state level. New York City licenses and "
            "registers contractors through its Department of Buildings, and other cities and counties run "
            "their own schemes. Trade licences are local."
        ),
        "statute_reference": "New York City Administrative Code Title 28; local codes elsewhere",
        "effective_date": None,
    },
    # ── State rules ──────────────────────────────────────────────────────────
    "state_rules": STATE_RULES,
    # ── Payment clock regimes this state seeds ───────────────────────────────
    "payment_clock_regimes": ["us_ny_public_state_179f", "us_ny_public_local_106b", "us_ny_private_756a"],
    # ── VAT rates ────────────────────────────────────────────────────────────
    "vat_rates": {},
}

# ── Statutory tables for the neutral engines ─────────────────────────────────
JURISDICTION_RULES: dict[str, Any] = {
    "code": "US-NY",
    "name": "New York",
    "country": "US",
    "backend_module": "oe_us_ny_pack",
    "verify_note": VERIFY_NOTE,
    "sectors": US_SECTORS,
    "claimant_roles": US_CLAIMANT_ROLES,
    "project_types": ["nonresidential", "residential", "single_family"],
    "notice_calendar": [
        {
            "code": "ny_lien_filing",
            "name": "File notice of lien",
            "kind": "lien",
            "rule_type": "months_after_event",
            "event": "last_work",
            "months": 8,
            "project_types": ["nonresidential", "residential"],
            "source": "N.Y. Lien Law § 10",
            "source_url": _LIEN_LAW_10_URL,
        },
        {
            "code": "ny_lien_filing_single_family",
            "name": "File notice of lien (single family dwelling or unit)",
            "kind": "lien",
            "rule_type": "months_after_event",
            "event": "last_work",
            "months": 4,
            "project_types": ["single_family"],
            "source": "N.Y. Lien Law § 10",
            "source_url": _LIEN_LAW_10_URL,
        },
    ],
    "retention": [
        {
            "code": "ny_private_retainage_cap",
            "kind": "cap",
            "pct": NY_PRIVATE_RETAINAGE_CAP_PCT,
            "sectors": ["private"],
            "min_contract_value": NY_PRIVATE_RETAINAGE_MIN_CONTRACT_USD,
            "agreement_date_from": "2023-11-17",
            "source": "N.Y. Gen. Bus. Law §§ 756-c, 757",
        },
        {
            "code": "ny_public_retainage_cap",
            "kind": "cap",
            "pct": "5",
            "sectors": ["public"],
            "source": "N.Y. State Fin. Law § 139-f; Gen. Mun. Law § 106-b",
        },
    ],
    "tax": {
        "base_rate_pct": NY_STATE_SALES_TAX_PCT,
        "rate_lookup_url": "https://www.tax.ny.gov/pdf/publications/sales/pub718.pdf",
        "item_classes": ["material", "fixture", "labor", "equipment"],
        "contract_forms": {
            "capital_improvement": {
                "label": "Capital improvement",
                "source": "N.Y. Tax Law § 1105(c)(3); TB-ST-104",
                "exemption_certificate": "ST-124",
                "description": "The contractor pays tax on materials; the customer is charged none with an ST-124.",
                "treatment": {
                    "material": "consumer",
                    "fixture": "consumer",
                    "labor": "exempt",
                    "equipment": "consumer",
                    "other": "consumer",
                },
            },
            "repair_maintenance": {
                "label": "Repair or maintenance",
                "source": "N.Y. Tax Law § 1105(c)(3), (5)",
                "description": "The whole charge, labor included, is taxed to the customer.",
                "treatment": {
                    "material": "retailer_collected",
                    "fixture": "retailer_collected",
                    "labor": "retailer_collected",
                    "equipment": "retailer_collected",
                    "other": "retailer_collected",
                },
            },
        },
    },
    "payroll_export_profiles": ["ny_dol_payroll_xml", "us_wh347_csv"],
    "links": [
        {"label": "Tax rate lookup", "url": "https://www.tax.ny.gov/pdf/publications/sales/pub718.pdf"},
        {"label": "Electronic payroll", "url": "https://dol.ny.gov/Electronic-Payroll"},
    ],
    "validation_rules": [
        *common_bindings(),
        {
            "id": "ny.tax.capital_improvement_no_st124",
            "check": "tax.exemption_certificate_missing",
            "severity": "error",
            "name": "Capital improvement without ST-124",
            "message": "Capital improvement priced tax-free but no ST-124 on file.",
        },
        {
            "id": "ny.pw.schedule_missing",
            "check": "wage.determination_missing",
            "severity": "error",
            "name": "New York public work without a wage schedule",
            "message": "Public work in NY without a NYSDOL or Comptroller schedule.",
            "params": {"accepted_authorities": ["state", "city"]},
        },
    ],
}
