# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for the State of Florida.

Same ownership split as the other state packs: federal and nationwide rules stay
in ``app.modules.us_pack.config``; this module carries what changes in Florida.
``vat_rates`` is empty for the same reason it is in ``us_pack``.

Three Florida rules move money on an ordinary bid. The contractor under a lump
sum contract is the ultimate consumer of the materials it installs, so the tax is
a cost inside the price. The county discretionary surtax reaches only the first
5,000 dollars of any single item, so one large piece of equipment is surtaxed on
5,000 dollars and no more. And a lienor not in privity with the owner loses its
lien unless it serves a notice to owner within 45 days of first furnishing.

Florida has no state prevailing wage statute. From 30 September 2026 a political
subdivision may not use its contracting to control the wages its contractors pay;
federal Davis-Bacon rates still apply where federal money funds the work.

County surtax rates are published yearly on form DR-15DSS and are an input, like
every address rate. No county rate is carried here.
"""

from typing import Any

from app.modules.us_pack.statutory import US_CLAIMANT_ROLES, US_SECTORS, VERIFY_NOTE, common_bindings

FL_STATE_SALES_TAX_PCT = "6"
FL_SURTAX_ITEM_CAP_USD = "5000"
FL_PUBLIC_RETAINAGE_CAP_PCT = "5"
FL_PUBLIC_RETAINAGE_THRESHOLD_USD = "200000"
FL_LIEN_LAW_EXEMPT_CONTRACT_USD = "2500"

_FS = "https://www.flsenate.gov/Laws/Statutes/2025/"

STATE_RULES: dict[str, list[dict[str, Any]]] = {
    # ── Sales and use tax ────────────────────────────────────────────────────
    "sales_tax": [
        {
            "code": "fl_state_rate",
            "name": "State sales and use tax rate",
            "description": (
                "The state rate is 6 percent. Most counties add a discretionary sales surtax, published each year "
                "on form DR-15DSS and applied where the goods are delivered."
            ),
            "value": FL_STATE_SALES_TAX_PCT,
            "unit": "percent",
            "statute_reference": "Florida Statutes § 212.05",
            "effective_date": None,
        },
        {
            "code": "fl_contractor_ultimate_consumer",
            "name": "Lump sum: the contractor is the ultimate consumer",
            "description": (
                "Under a lump sum, cost plus or guaranteed price contract the contractor is the ultimate consumer "
                "of the materials it incorporates into real property and pays tax when it buys them. The customer "
                "is not charged tax on the contract."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "Florida Administrative Code Rule 12A-1.051",
            "source_url": "https://www.flrules.org/gateway/ruleNo.asp?id=12A-1.051",
            "effective_date": None,
        },
        {
            "code": "fl_retail_sale_plus_installation",
            "name": "Retail sale plus installation: the customer pays",
            "description": (
                "Where the contractor sells the goods at retail and then installs them, the contractor is a dealer: "
                "it collects tax from the customer on the sale price of the goods, and the installation labor is "
                "not taxed when separately stated."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "Florida Administrative Code Rule 12A-1.051",
            "source_url": "https://www.flrules.org/gateway/ruleNo.asp?id=12A-1.051",
            "effective_date": None,
        },
        {
            "code": "fl_surtax_single_item_cap",
            "name": "Surtax reaches the first 5,000 dollars of a single item",
            "description": (
                "The county discretionary sales surtax applies only to the first 5,000 dollars of the sales "
                "amount of any single item of tangible personal property. A 60,000 dollar chiller is surtaxed on "
                "5,000 dollars."
            ),
            "value": FL_SURTAX_ITEM_CAP_USD,
            "unit": "usd",
            "statute_reference": "Florida Statutes § 212.054(2)(b)1",
            "source_url": _FS + "212.054",
            "effective_date": None,
        },
    ],
    # ── Prevailing wage ──────────────────────────────────────────────────────
    "prevailing_wage": [
        {
            "code": "fl_no_state_prevailing_wage",
            "name": "No state prevailing wage law",
            "description": (
                "Florida has no state prevailing wage statute. Federal Davis-Bacon rates apply only where the work "
                "is paid for with federal money."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "No Florida statute; Davis-Bacon Act, 40 U.S.C. §§ 3141-3148, where federally funded",
            "effective_date": None,
        },
        {
            "code": "fl_local_wage_preemption",
            "name": "Local wage terms in contracts are preempted",
            "description": (
                "A political subdivision may not, through its purchasing or contracting, seek to control or affect "
                "the wages or employment benefits its contractors provide. The amendment applies from 30 September "
                "2026 and does not impair a contract entered into before that date."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "Florida Statutes § 218.077, as amended by ch. 2024-80, Laws of Florida",
            "source_url": _FS + "218.077",
            "effective_date": "2026-09-30",
        },
    ],
    # ── Retainage ────────────────────────────────────────────────────────────
    "retainage": [
        {
            "code": "fl_public_local_retainage_cap",
            "name": "Local public retainage capped at 5 percent",
            "description": (
                "A local governmental entity may withhold no more than 5 percent of each progress payment as "
                "retainage on a construction services contract. The section does not reach a contract whose total "
                "cost is 200,000 dollars or less."
            ),
            "value": FL_PUBLIC_RETAINAGE_CAP_PCT,
            "unit": "percent",
            "works": "public",
            "applies_when_contract_value_usd_above": FL_PUBLIC_RETAINAGE_THRESHOLD_USD,
            "statute_reference": "Florida Statutes § 218.735(8)",
            "source_url": _FS + "218.735",
            "effective_date": None,
        },
        {
            "code": "fl_public_state_retainage_cap",
            "name": "State public retainage capped at 5 percent",
            "description": "The same 5 percent cap applies to state construction contracts over 200,000 dollars.",
            "value": FL_PUBLIC_RETAINAGE_CAP_PCT,
            "unit": "percent",
            "works": "public",
            "statute_reference": "Florida Statutes § 255.078",
            "source_url": "https://m.flsenate.gov/statutes/255.078",
            "effective_date": None,
        },
        {
            "code": "fl_private_retainage_contract_governs",
            "name": "Private retainage: the contract governs",
            "description": (
                "No statute caps retainage on private work. The balance of the contract price, retainage included, "
                "is due within 14 days after substantial completion is certified or a certificate of occupancy "
                "issues and the punch list is done."
            ),
            "value": "14",
            "unit": "days",
            "statute_reference": "Florida Statutes § 715.12",
            "source_url": _FS + "715.12",
            "effective_date": None,
        },
    ],
    # ── Prompt payment ───────────────────────────────────────────────────────
    "prompt_payment": [
        {
            "code": "fl_local_public_payment",
            "name": "Local public owner pays in 20 business days",
            "description": (
                "Payment is due 20 business days after the payment request is stamped as received, or 25 business "
                "days where an agent must approve it first. Late payments carry 2 percent a month."
            ),
            "value": "20",
            "unit": "business_days",
            "agent_approval_business_days": "25",
            "payment_clock_regime": "us_fl_public_local_218735",
            "statute_reference": "Florida Statutes § 218.735(1) and (9)",
            "source_url": _FS + "218.735",
            "effective_date": None,
        },
        {
            "code": "fl_private_payment",
            "name": "Private payment: the contract governs",
            "description": (
                "The private prompt payment statute sets no day count of its own; the contract does. Late payment "
                "carries interest at the rate under section 55.03 plus 12 percent a year, from the 14th day after "
                "payment was due."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "Florida Statutes § 715.12",
            "source_url": _FS + "715.12",
            "effective_date": None,
        },
    ],
    # ── Construction lien ────────────────────────────────────────────────────
    "lien": [
        {
            "code": "fl_notice_to_owner",
            "name": "Notice to owner within 45 days",
            "description": (
                "A lienor not in privity with the owner must serve a notice to owner before commencing, or not "
                "later than 45 days after commencing, to furnish labor, services or materials, and in any event "
                "before the owner's final payment. Without it the lien is lost."
            ),
            "value": "45",
            "unit": "days",
            "statute_reference": "Florida Statutes § 713.06(2)(a)",
            "source_url": _FS + "713.06",
            "effective_date": None,
        },
        {
            "code": "fl_claim_of_lien",
            "name": "Record the claim of lien within 90 days",
            "description": (
                "The claim of lien may be recorded at any time during the work and not later than 90 days after "
                "final furnishing, and must be served on the owner within 15 days after recording."
            ),
            "value": "90",
            "unit": "days",
            "service_days_after_recording": "15",
            "statute_reference": "Florida Statutes § 713.08(4)(c) and (5)",
            "source_url": _FS + "713.08",
            "effective_date": None,
        },
        {
            "code": "fl_lien_duration",
            "name": "The lien lasts one year",
            "description": (
                "A lien does not continue longer than 1 year after the claim of lien is recorded unless an action "
                "to enforce it is started within that time."
            ),
            "value": "1",
            "unit": "years",
            "statute_reference": "Florida Statutes § 713.22(1)",
            "source_url": _FS + "713.22",
            "effective_date": None,
        },
        {
            "code": "fl_contractor_final_affidavit",
            "name": "Contractor's final payment affidavit",
            "description": (
                "When final payment becomes due the contractor gives the owner a final payment affidavit listing "
                "any unpaid lienors who served a notice to owner, at least 5 days before starting an action to "
                "enforce its lien."
            ),
            "value": "5",
            "unit": "days",
            "statute_reference": "Florida Statutes § 713.06(3)(d)",
            "source_url": _FS + "713.06",
            "effective_date": None,
        },
        {
            "code": "fl_small_improvement_exemption",
            "name": "Improvements of 2,500 dollars or less",
            "description": (
                "An improvement whose direct contract price is 2,500 dollars or less is exempt from the lien part "
                "of the chapter except section 713.05, so the notice of commencement and notice to owner machinery "
                "does not apply to it."
            ),
            "value": FL_LIEN_LAW_EXEMPT_CONTRACT_USD,
            "unit": "usd",
            "statute_reference": "Florida Statutes § 713.02(5)",
            "source_url": _FS + "713.02",
            "effective_date": None,
        },
    ],
}

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "US_FL",
    "subdivision_code": "US-FL",
    "subdivision_name": "Florida",
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
        "state_general_contractor_licence": True,
        "note": (
            "Florida licenses general, building and residential contractors at state level through the "
            "Construction Industry Licensing Board, either certified (statewide) or registered (local). The "
            "platform records the licence number for reference and does not verify it."
        ),
        "statute_reference": "Florida Statutes Chapter 489, Part I",
        "effective_date": None,
    },
    # ── State rules ──────────────────────────────────────────────────────────
    "state_rules": STATE_RULES,
    # ── Payment clock regimes this state seeds ───────────────────────────────
    "payment_clock_regimes": ["us_fl_public_local_218735"],
    # ── VAT rates ────────────────────────────────────────────────────────────
    "vat_rates": {},
}

# ── Statutory tables for the neutral engines ─────────────────────────────────
JURISDICTION_RULES: dict[str, Any] = {
    "code": "US-FL",
    "name": "Florida",
    "country": "US",
    "backend_module": "oe_us_fl_pack",
    "verify_note": VERIFY_NOTE,
    "sectors": US_SECTORS,
    "claimant_roles": US_CLAIMANT_ROLES,
    "project_types": ["nonresidential", "residential"],
    "notice_calendar": [
        {
            "code": "fl_notice_to_owner",
            "name": "Serve notice to owner",
            "kind": "notice",
            "rule_type": "days_after_event",
            "event": "first_furnishing",
            "days": 45,
            "claimant_roles": ["subcontractor", "supplier"],
            "source": "Fla. Stat. § 713.06(2)(a)",
            "source_url": _FS + "713.06",
        },
        {
            "code": "fl_claim_of_lien",
            "name": "Record claim of lien",
            "kind": "lien",
            "rule_type": "days_after_event",
            "event": "final_furnishing",
            "days": 90,
            "source": "Fla. Stat. § 713.08(5)",
            "source_url": _FS + "713.08",
        },
        {
            "code": "fl_claim_service",
            "name": "Serve the recorded claim on the owner",
            "kind": "lien",
            "rule_type": "days_after_event",
            "event": "claim_recorded",
            "days": 15,
            "source": "Fla. Stat. § 713.08(4)(c)",
            "source_url": _FS + "713.08",
        },
        {
            "code": "fl_lien_enforcement",
            "name": "Start the action to enforce the lien",
            "kind": "suit",
            "rule_type": "months_after_event",
            "event": "claim_recorded",
            "months": 12,
            "source": "Fla. Stat. § 713.22(1)",
            "source_url": _FS + "713.22",
        },
        {
            "code": "fl_final_affidavit",
            "name": "Give the contractor's final payment affidavit",
            "kind": "notice",
            "rule_type": "days_after_event",
            "event": "planned_suit_filing",
            "days": -5,
            "claimant_roles": ["direct_contractor"],
            "source": "Fla. Stat. § 713.06(3)(d)",
            "source_url": _FS + "713.06",
        },
    ],
    "retention": [
        {
            "code": "fl_public_retainage_cap",
            "kind": "cap",
            "pct": FL_PUBLIC_RETAINAGE_CAP_PCT,
            "sectors": ["public"],
            "min_contract_value": FL_PUBLIC_RETAINAGE_THRESHOLD_USD,
            "min_inclusive": False,
            "source": "Fla. Stat. §§ 218.735(8), 255.078",
        },
    ],
    "tax": {
        "base_rate_pct": FL_STATE_SALES_TAX_PCT,
        "rate_lookup_url": "https://floridarevenue.com/Forms_library/current/dr15dss.pdf",
        "item_classes": ["material", "fixture", "labor", "equipment"],
        "surtax": {"item_cap": FL_SURTAX_ITEM_CAP_USD, "source": "Fla. Stat. § 212.054(2)(b)1"},
        "contract_forms": {
            "lump_sum": {
                "label": "Lump sum",
                "source": "Fla. Admin. Code R. 12A-1.051",
                "description": "The contractor is the ultimate consumer of materials and pays the tax.",
                "treatment": {
                    "material": "consumer",
                    "fixture": "consumer",
                    "labor": "untaxed",
                    "equipment": "consumer",
                    "other": "consumer",
                },
            },
            "retail_sale_plus_installation": {
                "label": "Retail sale plus installation",
                "source": "Fla. Admin. Code R. 12A-1.051",
                "description": "The contractor sells the goods at retail and collects tax; labor is untaxed.",
                "treatment": {
                    "material": "retailer_collected",
                    "fixture": "retailer_collected",
                    "labor": "untaxed",
                    "equipment": "consumer",
                    "other": "consumer",
                },
            },
        },
    },
    "payroll_export_profiles": ["us_wh347_csv"],
    "contract_clauses": ["local_wage_clause"],
    "links": [
        {
            "label": "County surtax rates (DR-15DSS)",
            "url": "https://floridarevenue.com/Forms_library/current/dr15dss.pdf",
        },
    ],
    "validation_rules": [
        *common_bindings(),
        {
            "id": "fl.tax.surtax_over_item_cap",
            "check": "tax.surtax_over_item_cap",
            "severity": "warning",
            "name": "Surtax above the single item cap",
            "message": "Surtax applied above $5,000 on a single item.",
        },
        {
            "id": "fl.pw.local_wage_clause",
            "check": "contract.preempted_clause",
            "severity": "info",
            "name": "Local wage clause preempted",
            "message": "Local wage clause in a contract dated from 30.09.2026 is preempted (FS 218.077).",
            "params": {"clause": "local_wage_clause", "agreement_date_from": "2026-09-30"},
        },
    ],
}
