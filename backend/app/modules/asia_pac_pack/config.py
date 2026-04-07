"""Regional configuration for Asia-Pacific (AU, NZ, JP, SG)."""

from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "APAC",
    "countries": ["AU", "NZ", "JP", "SG", "HK", "MY"],
    "default_currency": "AUD",
    "supported_currencies": ["AUD", "NZD", "JPY", "SGD", "HKD", "MYR"],
    "default_locale": "en-AU",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "DD/MM/YYYY",
    "number_format": "1,234.56",
    # ── Standards — Australia ────────────────────────────────────────────────
    "standards": [
        {
            "code": "AIQS",
            "name": "AIQS — Australian Institute of Quantity Surveyors",
            "country": "AU",
            "description": "Professional standards for quantity surveying in Australia",
        },
        {
            "code": "RAWLINSONS",
            "name": "Rawlinsons Australian Construction Handbook",
            "country": "AU",
            "description": (
                "Annual cost reference for Australian construction, "
                "including elemental cost plans and trade rates"
            ),
        },
        {
            "code": "NATSPEC",
            "name": "NATSPEC — National Specification System",
            "country": "AU",
            "description": (
                "National building specification system maintained by "
                "Construction Information Systems Limited"
            ),
        },
        {
            "code": "ASMM",
            "name": "Australian Standard Method of Measurement of Building Works",
            "country": "AU",
            "description": "5th edition — standard measurement rules for building works",
        },
        # ── Standards — New Zealand ──────────────────────────────────────────
        {
            "code": "NZIQS",
            "name": "NZIQS — NZ Institute of Quantity Surveyors",
            "country": "NZ",
            "description": "Professional standards for quantity surveying in New Zealand",
        },
        {
            "code": "NZS_3910",
            "name": "NZS 3910 — Conditions of Contract for Building and Civil",
            "country": "NZ",
            "description": "Standard form of contract widely used in NZ construction",
        },
        # ── Standards — Japan ────────────────────────────────────────────────
        {
            "code": "SEKKISAN",
            "name": "積算基準 (Sekkisan Kijun) — Construction Cost Estimation Standards",
            "country": "JP",
            "description": (
                "Japanese government cost estimation standards published by "
                "the Ministry of Land, Infrastructure, Transport and Tourism (MLIT)"
            ),
        },
        {
            "code": "JBCI",
            "name": "JBCI — Japan Building Cost Information",
            "country": "JP",
            "description": "Construction cost indices published by the Building Research Institute",
        },
        {
            "code": "KENCHIKU_SEKISAN",
            "name": "建築積算 (Kenchiku Sekkisan) — Building Quantity Surveying",
            "country": "JP",
            "description": "Professional standards by BSIJ (Building Surveyors Institute of Japan)",
        },
        # ── Standards — Singapore ────────────────────────────────────────────
        {
            "code": "BCA_SG",
            "name": "BCA — Building and Construction Authority (Singapore)",
            "country": "SG",
            "description": "Regulatory standards and buildability/constructability framework",
        },
        {
            "code": "SISV",
            "name": "SISV — Singapore Institute of Surveyors and Valuers",
            "country": "SG",
            "description": "Professional measurement and cost standards for Singapore",
        },
        {
            "code": "SMM_SG",
            "name": "SMM — Singapore Standard Method of Measurement",
            "country": "SG",
            "description": "Measurement rules for building works in Singapore",
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "AS_4000",
            "name": "AS 4000 — General Conditions of Contract",
            "country": "AU",
            "description": "Standards Australia general conditions for construction",
        },
        {
            "code": "AS_4902",
            "name": "AS 4902 — Design and Construct",
            "country": "AU",
            "description": "Standards Australia design-and-construct contract",
        },
        {
            "code": "ABIC_MW",
            "name": "ABIC MW — Major Works Contract",
            "country": "AU",
            "description": "Australian Building Industry Contract for major works",
        },
        {
            "code": "NZS_3910_CONTRACT",
            "name": "NZS 3910 — Standard Contract",
            "country": "NZ",
            "description": "NZ standard conditions of contract for building and civil",
        },
        {
            "code": "PSSCOC_SG",
            "name": "PSSCOC — Public Sector Standard Conditions of Contract",
            "country": "SG",
            "description": "Singapore public sector standard contract conditions",
        },
        {
            "code": "SIA_SG",
            "name": "SIA — Singapore Institute of Architects Conditions",
            "country": "SG",
            "description": "Standard private-sector building contract in Singapore",
        },
    ],
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "AU_GST",
            "name": "Australia GST",
            "type": "gst",
            "country": "AU",
            "rate_pct": "10",
        },
        {
            "code": "NZ_GST",
            "name": "New Zealand GST",
            "type": "gst",
            "country": "NZ",
            "rate_pct": "15",
        },
        {
            "code": "JP_CONSUMPTION_TAX",
            "name": "Japan Consumption Tax (消費税)",
            "type": "consumption_tax",
            "country": "JP",
            "rate_pct": "10",
            "reduced_rate_pct": "8",
            "note": "Reduced rate applies to food and newspaper subscriptions",
        },
        {
            "code": "SG_GST",
            "name": "Singapore GST",
            "type": "gst",
            "country": "SG",
            "rate_pct": "9",
            "effective_from": "2024-01-01",
            "note": "Increased from 8% to 9% in January 2024",
        },
        {
            "code": "HK_NO_GST",
            "name": "Hong Kong — No GST/VAT",
            "type": "none",
            "country": "HK",
            "rate_pct": "0",
            "note": "Hong Kong does not levy a general sales tax or VAT",
        },
        {
            "code": "MY_SST",
            "name": "Malaysia SST — Sales Tax",
            "type": "sales_tax",
            "country": "MY",
            "rate_pct": "10",
            "note": "Sales tax on manufactured goods; service tax is 8%",
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
    # ── Japan-specific units ─────────────────────────────────────────────────
    "japan_units": {
        "area_tsubo": {
            "name": "坪 (tsubo)",
            "to_m2": "3.30579",
            "description": "Traditional Japanese area unit, still used in real estate",
        },
        "area_jo": {
            "name": "畳 (jō)",
            "to_m2": "1.62",
            "description": "Tatami-mat area unit (varies by region)",
        },
    },
}
