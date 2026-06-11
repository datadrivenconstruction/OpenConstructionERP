"""‌⁠‍Regional configuration for the United Kingdom."""

from decimal import Decimal
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
            "name": "NRM 1 - Order of Cost Estimating and Cost Planning",
            "description": "RICS New Rules of Measurement for cost planning (2nd ed.)",
        },
        {
            "code": "NRM2",
            "name": "NRM 2 - Detailed Measurement for Building Works",
            "description": "RICS rules for detailed measurement / bills of quantities",
            # NRM 2 Part 3 tabulated work sections 1-41 (RICS, 2nd ed.).
            "measurement_groups": [
                {"number": "1", "title": "Preliminaries"},
                {
                    "number": "2",
                    "title": "Off-site manufactured materials, components and buildings",
                },
                {"number": "3", "title": "Demolitions"},
                {"number": "4", "title": "Alterations, repairs and conservation"},
                {"number": "5", "title": "Excavating and filling"},
                {"number": "6", "title": "Ground remediation and soil stabilisation"},
                {"number": "7", "title": "Piling"},
                {"number": "8", "title": "Underpinning"},
                {"number": "9", "title": "Diaphragm walls and embedded retaining walls"},
                {"number": "10", "title": "Crib walls, gabions and reinforced earth"},
                {"number": "11", "title": "In-situ concrete works"},
                {"number": "12", "title": "Precast/composite concrete"},
                {"number": "13", "title": "Precast concrete"},
                {"number": "14", "title": "Masonry"},
                {"number": "15", "title": "Structural metalwork"},
                {"number": "16", "title": "Carpentry"},
                {"number": "17", "title": "Sheet roof coverings"},
                {"number": "18", "title": "Tile and slate roof and wall coverings"},
                {"number": "19", "title": "Waterproofing"},
                {"number": "20", "title": "Proprietary linings and partitions"},
                {"number": "21", "title": "Cladding and covering"},
                {"number": "22", "title": "General joinery"},
                {"number": "23", "title": "Windows, screens and lights"},
                {"number": "24", "title": "Doors, shutters and hatches"},
                {"number": "25", "title": "Stairs, walkways and balustrades"},
                {"number": "26", "title": "Metalwork"},
                {"number": "27", "title": "Glazing"},
                {"number": "28", "title": "Floor, wall, ceiling and roof finishings"},
                {"number": "29", "title": "Decoration"},
                {"number": "30", "title": "Suspended ceilings"},
                {"number": "31", "title": "Insulation, fire stopping and fire protection"},
                {"number": "32", "title": "Furniture, fittings and equipment"},
                {"number": "33", "title": "Drainage above ground"},
                {"number": "34", "title": "Drainage below ground"},
                {"number": "35", "title": "Site works"},
                {"number": "36", "title": "Fencing"},
                {"number": "37", "title": "Soft landscaping"},
                {"number": "38", "title": "Mechanical services"},
                {"number": "39", "title": "Electrical services"},
                {"number": "40", "title": "Transportation"},
                {
                    "number": "41",
                    "title": (
                        "Builder's work in connection with mechanical, electrical and transportation installations"
                    ),
                },
            ],
        },
        {
            "code": "NRM3",
            "name": "NRM 3 - Order of Cost Estimating for Building Maintenance",
            "description": "RICS rules for lifecycle cost planning",
        },
        {
            "code": "SMM7",
            "name": "SMM7 - Standard Method of Measurement (legacy)",
            "description": "Legacy measurement standard, superseded by NRM2",
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "JCT_SBC",
            "name": "JCT SBC/Q - Standard Building Contract with Quantities",
            "description": "Lump-sum contract with bills of quantities (2024 ed.)",
        },
        {
            "code": "JCT_DB",
            "name": "JCT DB - Design and Build Contract",
            "description": "Design-and-build single-stage (2024 ed.)",
        },
        {
            "code": "JCT_MC",
            "name": "JCT MC - Management Contract",
            "description": "Management contracting route (2024 ed.)",
        },
        {
            "code": "JCT_MWD",
            "name": "JCT MWD - Minor Works with Contractor's Design",
            "description": "Suitable for smaller projects (2024 ed.)",
        },
        {
            "code": "NEC4_ECC",
            "name": "NEC4 ECC - Engineering and Construction Contract",
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
            "name": "NEC4 ECS - Engineering and Construction Subcontract",
            "description": "Back-to-back subcontract for NEC4 ECC",
        },
        {
            "code": "NEC4_TSC",
            "name": "NEC4 TSC - Term Service Contract",
            "description": "Term maintenance and service works",
        },
    ],
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "UK_VAT_STANDARD",
            "name": "VAT - Standard Rate",
            "type": "vat",
            "rate_pct": "20",
        },
        {
            "code": "UK_VAT_REDUCED",
            "name": "VAT - Reduced Rate",
            "type": "vat",
            "rate_pct": "5",
            "note": "Applies to certain energy-saving materials, residential renovations",
        },
        {
            "code": "UK_VAT_ZERO",
            "name": "VAT - Zero Rate",
            "type": "vat",
            "rate_pct": "0",
            "note": "New-build residential construction and approved alterations to listed buildings",
        },
        {
            "code": "UK_CIS_STANDARD",
            "name": "CIS - Standard Deduction",
            "type": "cis",
            "rate_pct": "20",
            "description": "Construction Industry Scheme withholding for registered subcontractors",
        },
        {
            "code": "UK_CIS_HIGHER",
            "name": "CIS - Higher Deduction",
            "type": "cis",
            "rate_pct": "30",
            "description": "CIS withholding for unregistered subcontractors",
        },
        {
            "code": "UK_CIS_GROSS",
            "name": "CIS - Gross Payment",
            "type": "cis",
            "rate_pct": "0",
            "description": "Gross payment status - no deduction",
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
            "name": "BCIS - Building Cost Information Service",
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
    # ── VAT rates (Wave 25 - HMRC VAT Notice 700) ────────────────────────────
    "vat_rates": {
        "GB": {
            "standard": Decimal("0.20"),
            "reduced": Decimal("0.05"),
            "zero": Decimal("0.00"),
        },
    },
}
