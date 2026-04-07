"""Regional configuration for India."""

from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "IN",
    "countries": ["IN"],
    "default_currency": "INR",
    "default_locale": "en-IN",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "DD/MM/YYYY",
    "number_format": "12,34,567.89",
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "IS",
            "name": "IS — Indian Standards (Bureau of Indian Standards)",
            "description": "National construction standards published by BIS",
            "key_codes": [
                {"code": "IS 456", "title": "Plain and Reinforced Concrete — Code of Practice"},
                {"code": "IS 800", "title": "General Construction in Steel — Code of Practice"},
                {"code": "IS 875", "title": "Code of Practice for Design Loads (Parts 1–5)"},
                {"code": "IS 1200", "title": "Method of Measurement of Building Works"},
                {"code": "IS 1893", "title": "Criteria for Earthquake Resistant Design"},
                {"code": "IS 2720", "title": "Methods of Test for Soils"},
                {"code": "IS 3370", "title": "Code of Practice for Concrete Structures (Liquid)"},
                {"code": "IS 4326", "title": "Earthquake Resistant Construction of Buildings"},
                {"code": "IS 13920", "title": "Ductile Design and Detailing of RC Structures"},
            ],
        },
        {
            "code": "NBC",
            "name": "NBC — National Building Code of India",
            "description": "Comprehensive building code covering all aspects of construction (2016 ed.)",
        },
        {
            "code": "IS_1200",
            "name": "IS 1200 — Method of Measurement of Building Works",
            "description": "Standard method of measurement for Indian construction",
            "parts": [
                {"part": "I", "title": "Earthwork"},
                {"part": "II", "title": "Concrete work"},
                {"part": "III", "title": "Brickwork"},
                {"part": "IV", "title": "Stonework"},
                {"part": "V", "title": "Formwork"},
                {"part": "VI", "title": "Steelwork"},
                {"part": "VII", "title": "Plastering and pointing"},
                {"part": "VIII", "title": "Woodwork and joinery"},
                {"part": "IX", "title": "Roofing"},
                {"part": "X", "title": "Flooring"},
                {"part": "XII", "title": "Painting"},
                {"part": "XIII", "title": "Whitewashing and colour washing"},
            ],
        },
    ],
    # ── Cost database references ─────────────────────────────────────────────
    "cost_database_references": [
        {
            "code": "CPWD",
            "name": "CPWD — Central Public Works Department",
            "description": (
                "Delhi Schedule of Rates (DSR) and analysis of rates "
                "published by CPWD; widely used as benchmark across India"
            ),
            "publications": [
                "Delhi Schedule of Rates (DSR)",
                "Analysis of Rates",
                "Plinth Area Rates",
                "CPWD Specifications",
            ],
        },
        {
            "code": "MES",
            "name": "MES — Military Engineer Services",
            "description": (
                "Schedule of rates for defence construction works; "
                "often referenced for government projects"
            ),
        },
        {
            "code": "STATE_PWD",
            "name": "State PWD Schedule of Rates",
            "description": (
                "Each Indian state publishes its own PWD schedule of rates "
                "(e.g., Maharashtra PWD, Karnataka PWD, Tamil Nadu PWD)"
            ),
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "CPWD_GCC",
            "name": "CPWD General Conditions of Contract",
            "description": "Standard government works contract conditions (2022 ed.)",
        },
        {
            "code": "FIDIC_IN",
            "name": "FIDIC Conditions (adapted for India)",
            "description": "FIDIC contracts adapted for Indian projects, common in multilateral-funded works",
        },
        {
            "code": "ITEM_RATE",
            "name": "Item Rate Contract",
            "description": "Payment based on measured quantities at tendered item rates",
        },
        {
            "code": "LUMP_SUM",
            "name": "Lump Sum Contract",
            "description": "Fixed-price contract for the complete scope of work",
        },
        {
            "code": "PERCENTAGE_RATE",
            "name": "Percentage Rate Contract",
            "description": "Rates expressed as percentage above/below schedule of rates",
        },
        {
            "code": "EPC",
            "name": "EPC — Engineering, Procurement, Construction",
            "description": "Turnkey contract for large infrastructure projects",
        },
        {
            "code": "PPP_BOT",
            "name": "PPP / BOT (Build-Operate-Transfer)",
            "description": "Public-private partnership model for infrastructure",
        },
    ],
    # ── Tax rules (GST multi-rate structure) ─────────────────────────────────
    "tax_rules": [
        {
            "code": "IN_GST_28",
            "name": "GST — 28% Slab",
            "type": "gst",
            "rate_pct": "28",
            "description": "Luxury goods, cement, paints, certain construction materials",
            "note": "Cement at 28%; steel at 18%",
        },
        {
            "code": "IN_GST_18",
            "name": "GST — 18% Slab",
            "type": "gst",
            "rate_pct": "18",
            "description": "Most construction services, steel, electrical fittings",
            "note": "Standard rate for works contracts",
        },
        {
            "code": "IN_GST_12",
            "name": "GST — 12% Slab",
            "type": "gst",
            "rate_pct": "12",
            "description": "Works contracts for government entities, affordable housing",
            "note": "Applicable to government/affordable housing works contracts",
        },
        {
            "code": "IN_GST_5",
            "name": "GST — 5% Slab",
            "type": "gst",
            "rate_pct": "5",
            "description": "Sand, marble, building bricks (certain categories)",
            "note": "Without input tax credit for certain construction services",
        },
        {
            "code": "IN_GST_0",
            "name": "GST — Exempt / 0% Slab",
            "type": "gst",
            "rate_pct": "0",
            "description": "Agricultural produce, certain essential materials",
        },
    ],
    # ── Payment milestones (typical) ─────────────────────────────────────────
    "payment_templates": [
        {
            "code": "RA_BILL",
            "name": "Running Account (RA) Bill",
            "description": (
                "Interim payment bill based on measured work; "
                "standard payment mechanism for government contracts"
            ),
            "fields": [
                "bill_number",
                "measurement_book_reference",
                "period",
                "gross_value_of_work",
                "secured_advance",
                "mobilisation_advance_recovery",
                "retention_pct",
                "retention_amount",
                "previous_payments",
                "net_amount_due",
                "gst",
                "tds_deduction",
                "total_payable",
            ],
        },
        {
            "code": "FINAL_BILL",
            "name": "Final Bill",
            "description": "Final measurement and settlement bill",
        },
    ],
    # ── Indian number formatting note ────────────────────────────────────────
    "number_system": {
        "name": "Indian numbering system",
        "description": "Uses lakh (1,00,000) and crore (1,00,00,000) grouping",
        "examples": [
            {"value": 100000, "formatted": "1,00,000", "word": "1 Lakh"},
            {"value": 10000000, "formatted": "1,00,00,000", "word": "1 Crore"},
        ],
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
