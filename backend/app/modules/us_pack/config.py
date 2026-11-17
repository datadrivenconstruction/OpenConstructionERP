# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for the United States."""

from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "US",
    "countries": ["US"],
    "default_currency": "USD",
    "default_locale": "en-US",
    "measurement_system": "imperial",
    "paper_size": "Letter",
    "date_format": "MM/DD/YYYY",
    "number_format": "1,234.56",
    # ── Exchange layouts: column names only, never rates, codes or values ────
    "equipment_rate_layout": {
        "label_key": "packs.us.equipment_layout",
        "interest_convention": "average_annual_investment",
        "decimal_comma": False,
        "mapping": {
            "code": "Code",
            "name": "Description",
            "category": "Category",
            "size_key": "Size",
            "value": "Purchase price",
            "residual": "Resale value",
            "life_years": "Life years",
            "months_per_year": "Months per year",
            "interest": "Interest",
            "repair": "Repair",
            "hours_per_month": "Hours per month",
        },
    },
    "payroll_profile": {
        "label_key": "packs.us.payroll_profile",
        "name": "Payroll US",
        "delimiter": ",",
        "decimal": ".",
        "date_format": "MM/DD/YYYY",
        "encoding": "utf-8",
        "grouping": "week",
        "week_start": 0,
        "columns": [
            {"header": "Employee ID", "source": "worker_ref"},
            {"header": "Week ending", "source": "date"},
            {"header": "Job", "source": "project_code"},
            {"header": "Cost code", "source": "cost_code"},
            {"header": "Pay code", "source": "pay_code"},
            {"header": "Hours", "source": "hours"},
        ],
    },
    # ── Standards ────────────────────────────────────────────────────────────
    # Division numbers are interoperability facts. The "scope" strings are our
    # own descriptions of the work each division covers - the proprietary
    # division titles must never be bundled (licensing denylist); users who
    # hold a licence import the official tables themselves.
    "standards": [
        {
            "code": "US_DIVISIONS",
            "name": "US specification division numbering",
            "description": "Division numbering for commercial/institutional construction",
            "divisions": [
                {"number": "00", "scope": "Bidding and contract-formation documents"},
                {"number": "01", "scope": "General project requirements and temporary provisions"},
                {"number": "02", "scope": "Demolition, site assessment and existing structures"},
                {"number": "03", "scope": "Cast-in-place and precast concrete work"},
                {"number": "04", "scope": "Brick, block and stone work"},
                {"number": "05", "scope": "Structural and miscellaneous metal work"},
                {"number": "06", "scope": "Carpentry, millwork and composite framing"},
                {"number": "07", "scope": "Roofing, waterproofing and insulation"},
                {"number": "08", "scope": "Doors, windows and glazed assemblies"},
                {"number": "09", "scope": "Interior finishing: drywall, flooring, painting"},
                {"number": "10", "scope": "Built-in specialty items and signage"},
                {"number": "11", "scope": "Fixed building equipment"},
                {"number": "12", "scope": "Furniture, casework and window treatments"},
                {"number": "13", "scope": "Pre-engineered and special-purpose structures"},
                {"number": "14", "scope": "Elevators, escalators and lifts"},
                {"number": "21", "scope": "Sprinkler and fire-suppression systems"},
                {"number": "22", "scope": "Piping systems and sanitary fixtures"},
                {"number": "23", "scope": "Heating, cooling and ventilation systems"},
                {"number": "25", "scope": "Building automation and controls integration"},
                {"number": "26", "scope": "Power distribution and lighting systems"},
                {"number": "27", "scope": "Voice, data and network cabling"},
                {"number": "28", "scope": "Fire alarm, access control and surveillance"},
                {"number": "31", "scope": "Excavation, grading and earth support"},
                {"number": "32", "scope": "Paving, landscaping and site amenities"},
                {"number": "33", "scope": "Site water, sewer, storm and power services"},
                {"number": "34", "scope": "Rail, transit and transportation infrastructure"},
                {"number": "35", "scope": "Marine, dredging and waterfront work"},
                {"number": "40", "scope": "Industrial process piping and interconnections"},
                {"number": "41", "scope": "Bulk material handling and processing plant"},
                {"number": "42", "scope": "Industrial process thermal equipment"},
                {"number": "43", "scope": "Industrial gas and liquid handling plant"},
                {"number": "44", "scope": "Emissions, effluent and waste treatment plant"},
                {"number": "45", "scope": "Manufacturing plant for specific industries"},
                {"number": "46", "scope": "Water and wastewater treatment plant"},
                {"number": "48", "scope": "On-site power generation plant"},
            ],
        },
        {
            "code": "US_ELEMENTAL",
            "name": "US elemental classification",
            "description": "Elemental classification for preliminary estimates (element names per NIST SP 841)",
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "AIA_A101",
            "name": "AIA A101 - Stipulated Sum",
            "description": "Standard owner-contractor agreement (fixed price)",
        },
        {
            "code": "AIA_A102",
            "name": "AIA A102 - Cost Plus Fee with GMP",
            "description": "Cost-plus with guaranteed maximum price",
        },
        {
            "code": "AIA_A201",
            "name": "AIA A201 - General Conditions",
            "description": "General conditions of the contract for construction",
        },
        {
            "code": "ConsensusDocs_200",
            "name": "ConsensusDocs 200 - Standard Agreement",
            "description": "Multi-party consensus-based standard agreement",
        },
    ],
    # ── Payment application format ───────────────────────────────────────────
    # Named generically: the well-known proprietary form identifiers are
    # trademarks and must not appear in code, UI or API (licensing denylist).
    # The field list below is arithmetic, which is not protectable.
    "payment_application": {
        "format": "US_PAY_APPLICATION",
        "name": "Application and Certificate for Payment",
        "description": (
            "Progress payment application with a schedule-of-values continuation sheet and a summary certificate"
        ),
        "fields": [
            "application_number",
            "period_to",
            "contract_sum",
            "change_orders",
            "adjusted_contract_sum",
            "completed_stored_previous",
            "completed_stored_this_period",
            "total_completed_stored",
            "retainage",
            "total_earned_less_retainage",
            "less_previous_certificates",
            "current_payment_due",
            "balance_to_finish",
        ],
    },
    # ── Progress billing ─────────────────────────────────────────────────────
    # Read through ``app.core.regional_packs.resolve_progress_billing``, keyed by
    # ISO country so a figure can only ever answer for the country it names.
    # Every number sits under a dict that says where it came from: a
    # ``statute_reference`` where a clause states it, ``source`` where it is
    # practice or our own convention, and ``effective_date`` always present
    # (``None`` = commencement not established, as in the state packs).
    # Contract-form clauses are cited by document and clause; the form numbers
    # of the payment and close-out forms stay out (see payment_application).
    "progress_billing": {
        "US": {
            "retention_policy": {
                "tiers": [
                    {"from_percent_complete": "0", "rate": "10"},
                    {"from_percent_complete": "50", "rate": "5"},
                ],
                "tier_mode": "prospective",
                "stored_materials_rate": None,
                "cap": None,
                "source": "industry_practice",
                "statute_reference": "AIA A101-2017 § 5.1.7.1 and § 5.1.7.2",
                "effective_date": None,
                "note": (
                    "The standard agreement leaves both the retainage figure and any reduction blank for the "
                    "parties to fill in, and says the amount may be limited by governing law. Ten percent "
                    "stepping down to five at half complete is the common pattern, not a national rule; some "
                    "states write the same split into statute for private work. Prospective mode keeps the "
                    "new rate for work done after the threshold, and a contract may choose recompute instead. "
                    "No separate stored-materials rate or national cap is suggested: the agreement takes one "
                    "retainage figure from each application, and caps are state law carried by the state packs."
                ),
            },
            "release_events": {
                "events": [
                    {
                        "event": "substantial_completion",
                        "release_percent_of_held": "100",
                        "open_items_withholding": {
                            "multiplier": "1.5",
                            "source": "industry_practice",
                            "effective_date": None,
                            "note": (
                                "The general conditions only say the payment is adjusted for incomplete work. "
                                "Holding back one and a half times the estimated cost of the open items is the "
                                "common measure and appears in several state prompt payment statutes; other "
                                "contracts write a different multiple."
                            ),
                        },
                        "required_documents": ["certificate_substantial_completion"],
                        "required_documents_when_bonded": ["consent_of_surety"],
                        "statute_reference": "AIA A201-2017 § 9.8.5",
                        "effective_date": "2017",
                    },
                    {
                        "event": "final_completion",
                        "release_percent_of_held": "100",
                        "required_documents": ["affidavit_payment_of_debts"],
                        "required_documents_when_bonded": ["consent_of_surety"],
                        "documents_owner_may_require": ["affidavit_release_of_liens", "final_lien_waiver"],
                        "statute_reference": "AIA A201-2017 § 9.10.2",
                        "effective_date": "2017",
                        "note": (
                            "The affidavit that payrolls, material bills and other indebtedness are paid and "
                            "the surety's consent to final payment are conditions of the remaining retainage. "
                            "Releases and waivers of liens are a condition only where the owner requires them, "
                            "which most owners do."
                        ),
                    },
                    {
                        "event": "rate_step_down",
                        "release_percent_of_held": None,
                        "required_documents": [],
                        "required_documents_when_bonded": ["consent_of_surety"],
                        "statute_reference": "AIA A101-2017 § 5.1.7.2 and its published instructions",
                        "effective_date": "2017",
                        "note": (
                            "A reduction of retainage before substantial completion needs the surety's consent "
                            "where the contractor furnished a bond. The amount released is whatever the "
                            "recompute leaves above the new rate, so no percentage is set here."
                        ),
                    },
                ],
            },
            "stored_materials": {
                "billable": True,
                "requirements_by_location_kind": {
                    "on_site": {
                        "any_of": [["delivery_ticket", "invoice"]],
                        "source": "industry_practice",
                        "statute_reference": "AIA A201-2017 § 9.3.2",
                        "effective_date": "2017",
                        "note": (
                            "Materials delivered and suitably stored at the site are billable, conditioned on "
                            "procedures satisfactory to the owner to establish its title or otherwise protect "
                            "its interest; a delivery ticket and the invoice are the usual proof."
                        ),
                    },
                    "off_site": {
                        "any_of": [["owner_approved_offsite", "bill_of_sale", "insurance"]],
                        "statute_reference": "AIA A201-2017 § 9.3.2",
                        "effective_date": "2017",
                        "note": (
                            "Off-site storage is billable only if the owner approved it in advance, at a "
                            "location agreed in writing, with the owner's title established and the goods "
                            "insured."
                        ),
                    },
                    "bonded_warehouse": {
                        "any_of": [["owner_approved_offsite", "bill_of_sale", "insurance"]],
                        "statute_reference": "AIA A201-2017 § 9.3.2",
                        "effective_date": "2017",
                    },
                    "supplier_premises": {
                        "any_of": [["owner_approved_offsite", "bill_of_sale", "insurance"]],
                        "statute_reference": "AIA A201-2017 § 9.3.2",
                        "effective_date": "2017",
                    },
                },
                "statute_reference": "AIA A201-2017 § 9.3.2",
                "effective_date": "2017",
            },
            "sub_payment_requirements": {
                # Summary the subcontractor rollup reads; ``requirements`` below
                # is the detail, and a test holds the two to the same names.
                "certificate_types": ["insurance", "license"],
                "lien_waiver_required": True,
                "source": "industry_practice",
                "statute_reference": "AIA A201-2017 § 9.3.1",
                "effective_date": "2017",
                # Optional subcontract document roles a US general contractor
                # often asks for. Offered as presets on the document policy;
                # nothing is required until the tenant adds one to its list.
                "document_presets": [
                    {
                        "role": "osha_safety_program",
                        "signed": False,
                        "label": "OSHA safety and health program",
                        "reference": "29 CFR 1926.20",
                    },
                    {
                        "role": "osha_training_records",
                        "signed": False,
                        "label": "OSHA training records",
                        "reference": "29 CFR 1926.21",
                    },
                    {
                        "role": "w9_tax_form",
                        "signed": True,
                        "label": "IRS Form W-9",
                        "reference": "IRS Form W-9",
                    },
                ],
                "requirements": [
                    {
                        "code": "insurance_certificate",
                        "evidence": "certificate",
                        "cert_type": "insurance",
                        "valid_at": "period_end",
                        "effect_if_missing": "hold_payment",
                        "source": "industry_practice",
                        "effective_date": None,
                    },
                    {
                        "code": "contractor_license",
                        "evidence": "certificate",
                        "cert_type": "license",
                        "valid_at": "period_end",
                        "effect_if_missing": "hold_payment",
                        "source": "state_law",
                        "effective_date": None,
                        "note": "Licensing is set state by state; the state packs carry the licensing duties.",
                    },
                    {
                        "code": "lien_waiver",
                        "evidence": "lien_waiver",
                        "waiver_types": {
                            "current_period": "conditional_partial",
                            "prior_paid_periods": "unconditional_partial",
                            "final": ["conditional_final", "unconditional_final"],
                        },
                        "effect_if_missing": "hold_payment",
                        "source": "industry_practice",
                        "statute_reference": "AIA A201-2017 § 9.3.1",
                        "effective_date": "2017",
                        "note": (
                            "The general conditions let the owner ask for releases and waivers of liens from "
                            "subcontractors and suppliers as support for each application. A conditional "
                            "waiver covers the payment now applied for and an unconditional one covers "
                            "payments already received; several states prescribe the wording."
                        ),
                    },
                ],
            },
            "billing_cycle": {
                "frequency": "monthly",
                "period_end": "month_end",
                "statute_reference": "AIA A101-2017 § 5.1.2",
                "effective_date": "2017",
                "note": "One calendar month ending on the last day of the month, unless the parties write another period.",
                "application_timing": {
                    "submit_days_before_payment_date": "10",
                    "architect_certifies_within_days": "7",
                    "statute_reference": "AIA A201-2017 § 9.3.1 and § 9.4.1",
                    "effective_date": "2017",
                },
                "payment_clock_regimes": {},
                "payment_clock_note": (
                    "No national payment period: the agreement leaves the payment date to the parties, and "
                    "statutory prompt payment periods are state law seeded by the state packs."
                ),
            },
            "change_line_code_format": {
                "format": "{source_code}",
                "placeholders": ["source_code"],
                "source": "platform_convention",
                "effective_date": None,
                "note": "A change-order line carries the change order's own code, for example CO-005.",
            },
        },
    },
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "US_SALES_TAX",
            "name": "State & Local Sales Tax",
            "type": "sales_tax",
            "description": "Combined state + local sales tax (varies by jurisdiction)",
            "note": "Construction materials taxability varies by state",
            "examples": [
                {"state": "NY", "combined_rate_pct": "8.875", "note": "NYC rate"},
                {"state": "CA", "combined_rate_pct": "7.250", "note": "State minimum"},
                {"state": "TX", "combined_rate_pct": "6.250", "note": "State rate"},
                {"state": "FL", "combined_rate_pct": "6.000", "note": "State rate"},
                {"state": "WA", "combined_rate_pct": "6.500", "note": "State rate"},
            ],
        },
        {
            "code": "US_USE_TAX",
            "name": "Use Tax",
            "type": "use_tax",
            "description": "Applies to out-of-state purchases; same rate as sales tax",
        },
    ],
    # ── Federal holidays reference ───────────────────────────────────────────
    "holidays_reference": [
        {"name": "New Year's Day", "date_rule": "January 1"},
        {"name": "Martin Luther King Jr. Day", "date_rule": "Third Monday in January"},
        {"name": "Presidents' Day", "date_rule": "Third Monday in February"},
        {"name": "Memorial Day", "date_rule": "Last Monday in May"},
        {"name": "Juneteenth", "date_rule": "June 19"},
        {"name": "Independence Day", "date_rule": "July 4"},
        {"name": "Labor Day", "date_rule": "First Monday in September"},
        {"name": "Columbus Day", "date_rule": "Second Monday in October"},
        {"name": "Veterans Day", "date_rule": "November 11"},
        {"name": "Thanksgiving Day", "date_rule": "Fourth Thursday in November"},
        {"name": "Christmas Day", "date_rule": "December 25"},
    ],
    # ── Cost database integration stubs ──────────────────────────────────────
    "cost_database_integrations": [
        {
            "code": "us_commercial_cost_data",
            "name": "US commercial cost database",
            "description": "US construction cost data with city cost indices",
            "api_base_url": "",
            "enabled": False,
            "note": "Requires a commercial US cost-data subscription and API key",
        },
    ],
    # ── Units (imperial defaults) ────────────────────────────────────────────
    "default_units": {
        "length": "ft",
        "area": "sf",
        "volume": "cf",
        "weight": "lbs",
        "temperature": "°F",
        "pressure": "psi",
    },
    # ── VAT rates (Wave 25) ──────────────────────────────────────────────────
    # US has no federal VAT - per-state sales tax is modelled in tax_rules.
    # Empty dict is the explicit signal that this pack opts out of VAT.
    "vat_rates": {},
}
