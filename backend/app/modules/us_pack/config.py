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
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "CSI_MasterFormat",
            "name": "CSI MasterFormat 2018",
            "description": "50 divisions for commercial/institutional construction",
            "divisions": [
                {"number": "00", "title": "Procurement and Contracting Requirements"},
                {"number": "01", "title": "General Requirements"},
                {"number": "02", "title": "Existing Conditions"},
                {"number": "03", "title": "Concrete"},
                {"number": "04", "title": "Masonry"},
                {"number": "05", "title": "Metals"},
                {"number": "06", "title": "Wood, Plastics, and Composites"},
                {"number": "07", "title": "Thermal and Moisture Protection"},
                {"number": "08", "title": "Openings"},
                {"number": "09", "title": "Finishes"},
                {"number": "10", "title": "Specialties"},
                {"number": "11", "title": "Equipment"},
                {"number": "12", "title": "Furnishings"},
                {"number": "13", "title": "Special Construction"},
                {"number": "14", "title": "Conveying Equipment"},
                {"number": "21", "title": "Fire Suppression"},
                {"number": "22", "title": "Plumbing"},
                {"number": "23", "title": "Heating, Ventilating, and Air Conditioning (HVAC)"},
                {"number": "25", "title": "Integrated Automation"},
                {"number": "26", "title": "Electrical"},
                {"number": "27", "title": "Communications"},
                {"number": "28", "title": "Electronic Safety and Security"},
                {"number": "31", "title": "Earthwork"},
                {"number": "32", "title": "Exterior Improvements"},
                {"number": "33", "title": "Utilities"},
                {"number": "34", "title": "Transportation"},
                {"number": "35", "title": "Waterway and Marine Construction"},
                {"number": "40", "title": "Process Interconnections"},
                {"number": "41", "title": "Material Processing and Handling Equipment"},
                {"number": "42", "title": "Process Heating, Cooling, and Drying Equipment"},
                {"number": "43", "title": "Process Gas and Liquid Handling"},
                {"number": "44", "title": "Pollution and Waste Control Equipment"},
                {"number": "46", "title": "Water and Wastewater Equipment"},
                {"number": "48", "title": "Electrical Power Generation"},
            ],
        },
        {
            "code": "CSI_UniFormat",
            "name": "CSI UniFormat II",
            "description": "Elemental classification for preliminary estimates",
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "AIA_A101",
            "name": "AIA A101 — Stipulated Sum",
            "description": "Standard owner-contractor agreement (fixed price)",
        },
        {
            "code": "AIA_A102",
            "name": "AIA A102 — Cost Plus Fee with GMP",
            "description": "Cost-plus with guaranteed maximum price",
        },
        {
            "code": "AIA_A201",
            "name": "AIA A201 — General Conditions",
            "description": "General conditions of the contract for construction",
        },
        {
            "code": "ConsensusDocs_200",
            "name": "ConsensusDocs 200 — Standard Agreement",
            "description": "Multi-party consensus-based standard agreement",
        },
    ],
    # ── Payment application format ───────────────────────────────────────────
    "payment_application": {
        "format": "AIA_G702_G703",
        "name": "AIA G702/G703 Application and Certificate for Payment",
        "description": (
            "Standard payment application with Schedule of Values (G703) "
            "and summary certificate (G702)"
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
            "code": "RSMeans",
            "name": "Gordian RSMeans",
            "description": "US construction cost data with city cost indices",
            "api_base_url": "",
            "enabled": False,
            "note": "Requires RSMeans Data Online subscription and API key",
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
}
