"""Regional configuration for the United Kingdom."""

from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "UK",
    "countries": ["GB"],
    "default_currency": "GBP",
    "default_locale": "en-GB",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "DD/MM/YYYY",
    "number_format": "1,234.56",
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "NRM1",
            "name": "NRM 1 — Order of Cost Estimating and Cost Planning",
            "description": "RICS New Rules of Measurement for cost planning (2nd ed.)",
        },
        {
            "code": "NRM2",
            "name": "NRM 2 — Detailed Measurement for Building Works",
            "description": "RICS rules for detailed measurement / bills of quantities",
            "measurement_groups": [
                {"number": "1", "title": "Preliminaries"},
                {"number": "2", "title": "Off-site manufactured materials"},
                {"number": "3", "title": "Demolitions"},
                {"number": "4", "title": "Groundworks"},
                {"number": "5", "title": "In-situ concrete works"},
                {"number": "6", "title": "Precast concrete"},
                {"number": "7", "title": "Masonry"},
                {"number": "8", "title": "Structural metalwork"},
                {"number": "9", "title": "Carpentry"},
                {"number": "10", "title": "Cladding and covering"},
                {"number": "11", "title": "Waterproofing"},
                {"number": "12", "title": "Proprietary linings and partitions"},
                {"number": "13", "title": "Doors"},
                {"number": "14", "title": "Windows"},
                {"number": "15", "title": "Stairs, walkways and balustrades"},
                {"number": "16", "title": "Metalwork (secondary)"},
                {"number": "17", "title": "Glazing"},
                {"number": "18", "title": "Floor, wall, ceiling finishings"},
                {"number": "19", "title": "Decoration"},
                {"number": "20", "title": "Suspended ceilings"},
                {"number": "21", "title": "Insulation"},
                {"number": "22", "title": "Furniture and fittings"},
                {"number": "23", "title": "Drainage below ground"},
                {"number": "24", "title": "Drainage above ground"},
                {"number": "25", "title": "Piped supply systems"},
                {"number": "26", "title": "Mechanical heating/cooling"},
                {"number": "27", "title": "Ventilation systems"},
                {"number": "28", "title": "Electrical installations"},
                {"number": "29", "title": "Fire and lightning protection"},
                {"number": "30", "title": "Communication/security installations"},
                {"number": "31", "title": "Transport installations"},
                {"number": "32", "title": "Builders work in connection with services"},
                {"number": "33", "title": "External works"},
                {"number": "34", "title": "Minor demolition / alteration works"},
            ],
        },
        {
            "code": "NRM3",
            "name": "NRM 3 — Order of Cost Estimating for Building Maintenance",
            "description": "RICS rules for lifecycle cost planning",
        },
        {
            "code": "SMM7",
            "name": "SMM7 — Standard Method of Measurement (legacy)",
            "description": "Legacy measurement standard, superseded by NRM2",
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "JCT_SBC",
            "name": "JCT SBC/Q — Standard Building Contract with Quantities",
            "description": "Lump-sum contract with bills of quantities (2024 ed.)",
        },
        {
            "code": "JCT_DB",
            "name": "JCT DB — Design and Build Contract",
            "description": "Design-and-build single-stage (2024 ed.)",
        },
        {
            "code": "JCT_MC",
            "name": "JCT MC — Management Contract",
            "description": "Management contracting route (2024 ed.)",
        },
        {
            "code": "JCT_MWD",
            "name": "JCT MWD — Minor Works with Contractor's Design",
            "description": "Suitable for smaller projects (2024 ed.)",
        },
        {
            "code": "NEC4_ECC",
            "name": "NEC4 ECC — Engineering and Construction Contract",
            "description": "Process-based contract with 6 main options (A–F)",
            "options": [
                {"code": "A", "title": "Priced contract with activity schedule"},
                {"code": "B", "title": "Priced contract with bill of quantities"},
                {"code": "C", "title": "Target contract with activity schedule"},
                {"code": "D", "title": "Target contract with bill of quantities"},
                {"code": "E", "title": "Cost reimbursable contract"},
                {"code": "F", "title": "Management contract"},
            ],
        },
        {
            "code": "NEC4_ECS",
            "name": "NEC4 ECS — Engineering and Construction Subcontract",
            "description": "Back-to-back subcontract for NEC4 ECC",
        },
        {
            "code": "NEC4_TSC",
            "name": "NEC4 TSC — Term Service Contract",
            "description": "Term maintenance and service works",
        },
    ],
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "UK_VAT_STANDARD",
            "name": "VAT — Standard Rate",
            "type": "vat",
            "rate_pct": "20",
        },
        {
            "code": "UK_VAT_REDUCED",
            "name": "VAT — Reduced Rate",
            "type": "vat",
            "rate_pct": "5",
            "note": "Applies to certain energy-saving materials, residential renovations",
        },
        {
            "code": "UK_VAT_ZERO",
            "name": "VAT — Zero Rate",
            "type": "vat",
            "rate_pct": "0",
            "note": "New-build residential construction and approved alterations to listed buildings",
        },
        {
            "code": "UK_CIS_STANDARD",
            "name": "CIS — Standard Deduction",
            "type": "cis",
            "rate_pct": "20",
            "description": "Construction Industry Scheme withholding for registered subcontractors",
        },
        {
            "code": "UK_CIS_HIGHER",
            "name": "CIS — Higher Deduction",
            "type": "cis",
            "rate_pct": "30",
            "description": "CIS withholding for unregistered subcontractors",
        },
        {
            "code": "UK_CIS_GROSS",
            "name": "CIS — Gross Payment",
            "type": "cis",
            "rate_pct": "0",
            "description": "Gross payment status — no deduction",
        },
    ],
    # ── Payment templates ────────────────────────────────────────────────────
    "payment_templates": [
        {
            "code": "INTERIM_VALUATION",
            "name": "Interim Valuation",
            "description": "Monthly or periodic interim valuation under JCT/NEC",
            "fields": [
                "valuation_number",
                "period_end_date",
                "gross_valuation",
                "retention_pct",
                "retention_amount",
                "less_previous_certificates",
                "amount_due",
                "cis_deduction",
                "net_payment",
                "vat",
                "total_certified",
            ],
        },
        {
            "code": "FINAL_ACCOUNT",
            "name": "Final Account",
            "description": "Agreed final account statement",
        },
    ],
    # ── Cost database references ─────────────────────────────────────────────
    "cost_database_references": [
        {
            "code": "BCIS",
            "name": "BCIS — Building Cost Information Service",
            "description": "RICS cost data with regional tender price indices",
        },
        {
            "code": "SPONS",
            "name": "Spon's Price Books",
            "description": "Annual UK construction price books",
        },
    ],
    # ── Units (metric defaults) ──────────────────────────────────────────────
    "default_units": {
        "length": "m",
        "area": "m²",
        "volume": "m³",
        "weight": "kg",
        "temperature": "°C",
    },
}
