"""Regional configuration for the Middle East and GCC countries."""

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
            "name": "CESMM4 — Civil Engineering Standard Method of Measurement",
            "description": "Widely used in GCC for civil and infrastructure works",
        },
        {
            "code": "POMI",
            "name": "POMI — Principles of Measurement International",
            "description": "RICS international measurement standard",
        },
        {
            "code": "ICMS",
            "name": "ICMS — International Construction Measurement Standards",
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
            "name": "Qatar — No VAT",
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
            "name": "Kuwait — No VAT",
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
}
