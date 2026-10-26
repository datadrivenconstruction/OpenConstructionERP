# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for the Middle East and GCC countries."""

from decimal import Decimal
from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "ME",
    "countries": ["AE", "SA", "QA", "KW", "BH", "OM", "JO", "EG"],
    "default_currency": "AED",
    "supported_currencies": ["AED", "SAR", "QAR", "KWD", "BHD", "OMR", "JOD", "EGP"],
    "default_locale": "ar",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "DD/MM/YYYY",
    "number_format": "1,234.56",
    # ── Calendar ─────────────────────────────────────────────────────────────
    "calendar": {
        "primary": "gregorian",
        "secondary": "hijri",
        "hijri_months": [
            {"number": 1, "name_ar": "مُحَرَّم", "name_en": "Muharram"},
            {"number": 2, "name_ar": "صَفَر", "name_en": "Safar"},
            {"number": 3, "name_ar": "رَبِيع الأوَّل", "name_en": "Rabi al-Awwal"},
            {"number": 4, "name_ar": "رَبِيع الثَّانِي", "name_en": "Rabi al-Thani"},
            {"number": 5, "name_ar": "جُمَادَىٰ الأُولَىٰ", "name_en": "Jumada al-Ula"},
            {"number": 6, "name_ar": "جُمَادَىٰ الثَّانِيَة", "name_en": "Jumada al-Thani"},
            {"number": 7, "name_ar": "رَجَب", "name_en": "Rajab"},
            {"number": 8, "name_ar": "شَعْبَان", "name_en": "Sha'ban"},
            {"number": 9, "name_ar": "رَمَضَان", "name_en": "Ramadan"},
            {"number": 10, "name_ar": "شَوَّال", "name_en": "Shawwal"},
            {"number": 11, "name_ar": "ذُو القَعْدَة", "name_en": "Dhu al-Qa'dah"},
            {"number": 12, "name_ar": "ذُو الحِجَّة", "name_en": "Dhu al-Hijjah"},
        ],
        "work_week": {
            "note": "Most GCC countries: Sun–Thu work week; Fri–Sat weekend",
            "work_days": ["sunday", "monday", "tuesday", "wednesday", "thursday"],
            "weekend_days": ["friday", "saturday"],
        },
    },
    # ── Ramadan work-hours adjustment ────────────────────────────────────────
    "ramadan_adjustment": {
        "enabled": True,
        "description": "During Ramadan, work hours are legally reduced in most GCC countries",
        "reduced_hours_per_day": 6,
        "normal_hours_per_day": 8,
        "note": "UAE: Federal Decree-Law No. 33/2021 Art. 17; KSA: Labour Law Art. 98",
    },
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "CESMM4",
            "name": "CESMM4 - Civil Engineering Standard Method of Measurement",
            "description": "Widely used in GCC for civil and infrastructure works",
        },
        {
            "code": "POMI",
            "name": "POMI - Principles of Measurement International",
            "description": "RICS international measurement standard",
        },
        {
            "code": "ICMS",
            "name": "ICMS - International Construction Measurement Standards",
            "description": "Global cost classification framework",
        },
    ],
    # ── Contract types (FIDIC) ───────────────────────────────────────────────
    "contract_types": [
        {
            "code": "FIDIC_RED",
            "name": "FIDIC Red Book (2017)",
            "name_ar": "كتاب فيديك الأحمر",
            "description": "Conditions of Contract for Construction (employer-designed)",
            "use_case": "Traditional design-bid-build projects",
        },
        {
            "code": "FIDIC_YELLOW",
            "name": "FIDIC Yellow Book (2017)",
            "name_ar": "كتاب فيديك الأصفر",
            "description": "Conditions of Contract for Plant and Design-Build",
            "use_case": "Design-build projects",
        },
        {
            "code": "FIDIC_SILVER",
            "name": "FIDIC Silver Book (2017)",
            "name_ar": "كتاب فيديك الفضي",
            "description": "Conditions of Contract for EPC/Turnkey Projects",
            "use_case": "Turnkey and EPC projects, risk shifted to contractor",
        },
        {
            "code": "FIDIC_GREEN",
            "name": "FIDIC Green Book (2021)",
            "name_ar": "كتاب فيديك الأخضر",
            "description": "Short Form of Contract for simple/low-value works",
            "use_case": "Small to medium projects",
        },
        {
            "code": "FIDIC_WHITE",
            "name": "FIDIC White Book (2017)",
            "name_ar": "كتاب فيديك الأبيض",
            "description": "Client/Consultant Model Services Agreement",
            "use_case": "Consultant appointments",
        },
    ],
    # ── Guarantee defaults ───────────────────────────────────────────────────
    # Read by app.modules.guarantees.defaults.defaults_for, laid over the FIDIC
    # 2017 figures per country. GCC practice: unconditional on-demand bank
    # guarantees from a locally licensed bank. Figures are usual entries, not
    # law, and were not checked against each published procurement text.
    "guarantee_defaults": {
        "AE": {
            "origin": "FIDIC 2017 with UAE practice",
            "types": {
                "bid_bond": {"percent_of_contract": "2", "form_code": "AE-BID-ONDEMAND"},
                "performance_bond": {
                    "percent_of_contract": "10",
                    "defects_period_months": 12,
                    "form_code": "AE-PB-ONDEMAND",
                    "note": "Unconditional on-demand form from a bank licensed by the UAE Central Bank.",
                },
                "advance_payment": {"percent_of_advance": "100", "form_code": "AE-APG-ONDEMAND"},
                "retention_bond": {"percent_of_contract": "5", "replaces_cash_retention": True},
            },
        },
        "SA": {
            "origin": "FIDIC 2017 with Saudi public procurement practice",
            "types": {
                "bid_bond": {
                    "percent_of_contract": "1",
                    "form_code": "SA-INITIAL-GUARANTEE",
                    "note": "Initial guarantee under the Government Tenders and Procurement Law (usual range 1 to 2 percent).",
                },
                "performance_bond": {
                    "percent_of_contract": "5",
                    "defects_period_months": 12,
                    "form_code": "SA-FINAL-GUARANTEE",
                    "note": "Final guarantee under the Government Tenders and Procurement Law.",
                },
                "advance_payment": {"percent_of_advance": "100", "form_code": "SA-APG"},
            },
        },
        "QA": {"origin": "FIDIC 2017 with GCC practice", "types": {"performance_bond": {"percent_of_contract": "10"}}},
        "KW": {"origin": "FIDIC 2017 with GCC practice", "types": {"performance_bond": {"percent_of_contract": "10"}}},
        "BH": {"origin": "FIDIC 2017 with GCC practice", "types": {"performance_bond": {"percent_of_contract": "10"}}},
        "OM": {"origin": "FIDIC 2017 with GCC practice", "types": {"performance_bond": {"percent_of_contract": "10"}}},
    },
    # ── Progress billing ─────────────────────────────────────────────────────
    # Read through ``app.core.regional_packs.resolve_progress_billing``. Keyed
    # per country, as in dach_pack: this pack claims eight countries and an
    # Egyptian figure must never answer for a Gulf one. Only EG is written.
    #
    # Egypt has no national retention or billing law for private works (they
    # follow FIDIC and the contract), so the block carries no retention tiers:
    # a tier here would be applied to every Egyptian contract at signing. The
    # public works figures of Law 182/2018 sit under ``public_client_`` keys,
    # and the contract defaults' public works variant applies them to a
    # project that records public works. Release events are left to the
    # contract defaults, which differ for public and private works.
    "progress_billing": {
        "EG": {
            "retention_policy": {
                "tiers": [],
                "rate_is_maximum": False,
                "tier_mode": "prospective",
                "stored_materials_rate": None,
                "cap": None,
                "source": "contractual",
                "effective_date": None,
                "note": (
                    "Private works take the retention their contract states, under FIDIC the percentage and "
                    "limit in the Contract Data; no Egyptian law sets either."
                ),
                "public_client_rate": {
                    "percent_of_executed_work": "5",
                    "paid_percent_of_executed_work": "95",
                    "release_event": "substantial_completion",
                    "substitute_security": "bank_guarantee",
                    "substitute_security_expires_days_after_release_event": "30",
                    "statute_reference": "Law 182/2018, Executive Regulations (Decree 692/2019), Art. 93",
                    "source_url": "https://eg.andersen.com/wp-content/uploads/2026/01/Law-No.-182-of-2018.pdf",
                    "read_date": "2026-10-19",
                    "effective_date": None,
                    "note": (
                        "On public works each interim pays 95 percent of the work executed and holds five "
                        "percent, payable against a local bank guarantee that expires 30 days after "
                        "provisional acceptance."
                    ),
                },
            },
            "stored_materials": {
                "billable": True,
                "source": "contractual",
                "effective_date": None,
                "note": "Private works bill stored materials as their contract agrees.",
                "public_client_valuation": {
                    "paid_percent_of_scheduled_value": "75",
                    "location_kinds": ["on_site"],
                    "conditions": ["approved", "properly_stored", "physical_inventory"],
                    "statute_reference": "Law 182/2018, Executive Regulations (Decree 692/2019), Art. 93",
                    "source_url": "https://eg.andersen.com/wp-content/uploads/2026/01/Law-No.-182-of-2018.pdf",
                    "read_date": "2026-10-19",
                    "effective_date": None,
                    "note": (
                        "On public works approved materials for the permanent works, properly stored on site "
                        "after a physical inventory, are paid at 75 percent of their scheduled value until "
                        "installed. The retention engine has no valuation percent for stored materials yet, so "
                        "this figure is shown, not applied."
                    ),
                },
            },
            "sub_payment_requirements": {
                "certificate_types": ["social_security_clearance"],
                "lien_waiver_required": False,
                "statute_reference": "Law 148/2019; MoSS Decree 152/2019, Arts. 200(1) and 206(3)",
                "effective_date": None,
                "requirements": [
                    {
                        "code": "social_insurance_clearance",
                        "evidence": "certificate",
                        "cert_type": "social_security_clearance",
                        "valid_at": "period_end",
                        "effect_if_missing": "hold_payment",
                        # Rule V19 of payment_release reads these four keys.
                        "gates": ["payment_release"],
                        "release_effect": "warn",
                        "applies_to_kinds": ["interim", "final"],
                        "needs_expert_review": True,
                        "statute_reference": "MoSS Decree 152/2019, Art. 206(3); Law 148/2019",
                        "source_url": "https://ahmedazimelgamel.blogspot.com/2019/08/152-2019.html",
                        "read_date": "2026-10-19",
                        "effective_date": None,
                        "note": (
                            "Each interim payment and the final payment on a construction contract wait until the "
                            "contractor shows a certificate from the National Organization for Social Insurance "
                            "that the contributions due on the contract are paid; the main contractor is jointly "
                            "liable for its subcontractors' contributions. Read in a reproduction of the decree, "
                            "and whether it stands unchanged under Law 148/2019 is not confirmed, so a missing "
                            "certificate warns instead of blocking until a company switches the contract to block."
                        ),
                    },
                ],
            },
            "billing_cycle": {
                "frequency": "monthly",
                "period_end": "month_end",
                "source": "industry_practice",
                "effective_date": None,
                "note": (
                    "Interim certificates (mustakhlas) are usually monthly; Law 182/2018 pays works by progress "
                    "and names no interval."
                ),
                "payment_clock_regimes": {
                    "public_works_interim": "eg_law182_works",
                    "public_supplies": "eg_law182_supplies",
                },
            },
        },
    },
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "UAE_VAT",
            "name": "UAE VAT",
            "type": "vat",
            "country": "AE",
            "rate_pct": "5",
            "effective_from": "2018-01-01",
        },
        {
            "code": "KSA_VAT",
            "name": "KSA VAT",
            "type": "vat",
            "country": "SA",
            "rate_pct": "15",
            "effective_from": "2020-07-01",
            "note": "Increased from 5% to 15% in July 2020",
        },
        {
            "code": "QA_VAT",
            "name": "Qatar - No VAT",
            "type": "vat",
            "country": "QA",
            "rate_pct": "0",
            "note": "Qatar has no VAT as of 2026",
        },
        {
            "code": "BH_VAT",
            "name": "Bahrain VAT",
            "type": "vat",
            "country": "BH",
            "rate_pct": "10",
            "effective_from": "2022-01-01",
            "note": "Increased from 5% to 10% in January 2022",
        },
        {
            "code": "OM_VAT",
            "name": "Oman VAT",
            "type": "vat",
            "country": "OM",
            "rate_pct": "5",
            "effective_from": "2021-04-16",
        },
        {
            "code": "KW_VAT",
            "name": "Kuwait - No VAT",
            "type": "vat",
            "country": "KW",
            "rate_pct": "0",
            "note": "Kuwait has not yet implemented VAT as of 2026",
        },
    ],
    # ── Bilingual PDF configuration ──────────────────────────────────────────
    "bilingual_pdf": {
        "enabled": True,
        "primary_language": "en",
        "secondary_language": "ar",
        "rtl_support": True,
        "font_families": {
            "arabic": "Noto Naskh Arabic",
            "english": "Inter",
        },
        "description": "All generated documents include both Arabic and English text",
    },
    # ── Units (metric defaults) ──────────────────────────────────────────────
    "default_units": {
        "length": "m",
        "area": "m²",
        "volume": "m³",
        "weight": "kg",
        "temperature": "°C",
    },
    # ── VAT rates (Wave 25 - GCC + AE / SA / BH / OM; QA & KW no VAT yet) ────
    "vat_rates": {
        "AE": {"standard": Decimal("0.05"), "zero": Decimal("0.00")},
        "SA": {"standard": Decimal("0.15"), "zero": Decimal("0.00")},
        "BH": {"standard": Decimal("0.10"), "zero": Decimal("0.00")},
        "OM": {"standard": Decimal("0.05"), "zero": Decimal("0.00")},
        "QA": {"standard": Decimal("0.00")},
        "KW": {"standard": Decimal("0.00")},
    },
}
