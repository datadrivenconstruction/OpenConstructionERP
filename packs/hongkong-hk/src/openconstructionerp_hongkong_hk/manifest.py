"""Build the ``PartnerPackManifest`` instance for the hongkong-hk pack."""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="hongkong-hk",
    partner_name="Hong Kong SAR Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for quantity surveyors and contractors in Hong Kong SAR: payment claims on the Security "
        "of Payment Ordinance (Cap. 652) clock with the 30-day response, the 60-day payment and the 28-day "
        "adjudication window, the CIC and CWR levies on works over HK$3,000,000, no VAT or GST line, the GCC "
        "retention defaults, bills coded to an HKSMM4 section skeleton, the ArchSD tender price indices for "
        "escalation, Traditional Chinese (Hong Kong) and English (Hong Kong), Hong Kong dollar."
    ),
    default_locale="zh-HK",
    additional_locales={"zh-HK": "locales/zh-HK.json", "en-HK": "locales/en-HK.json"},
    # No Hong Kong cost base is shipped: the ArchSD indices escalate a historic rate, they are not rates.
    cwicr_regions=[],
    default_currency="HKD",
    default_tax_template=None,
    default_methodology="hong-kong",
    validation_rule_packs=[
        "hk_sopo",
        "hk_levies",
    ],
    validation_rule_sets=["hongkong", "boq_quality"],
    default_modules=[
        "oe_boq",
        "oe_contracts",
        "oe_payment_clock",
        "oe_progress",
        "oe_finance",
        "oe_price_index",
        "oe_validation",
    ],
    hidden_modules=[],
    demo_template_ids=["hk-gov-office-fitout", "hk-residential-tuen-mun"],
    branding=PartnerBranding(
        primary_color="#DE2910",  # Hong Kong SAR flag red
        accent_color="#FFFFFF",
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "HK",
        "country_name_en": "Hong Kong SAR",
        "country_name_zh_hk": "香港特別行政區",
        "classification_standard": "hksmm4",
        "classification_codes_path": "data/hksmm4_skeleton.json",
        "price_index_snapshot_path": "data/archsd_tpi.json",
        "payment_regime": "hk_sopo",
        "regulator_refs": [
            "Construction Industry Security of Payment Ordinance (Cap. 652), in force for contracts made on or after 28 August 2025",
            "Construction Industry Council Ordinance (Cap. 587), Construction Industry Levy 0.5 percent",
            "Construction Workers Registration Ordinance (Cap. 583), levy 0.03 percent",
            "Buildings Ordinance (Cap. 123), s.14(1) approval and consent",
        ],
        # Form names only: the clause text belongs to the publishers and is never shipped.
        "contract_forms": [
            {
                "id": "gcc_building_1999",
                "name": "General Conditions of Contract for Building Works (HKSAR Government, 1999 edition)",
                "sector": "public",
            },
            {
                "id": "nec4_ecc",
                "name": "NEC4 Engineering and Construction Contract",
                "sector": "public",
                "note": "Used on many public works; a default to review, not a rule.",
            },
            {
                "id": "hkia_hkicm_private",
                "name": "Standard Form of Building Contract for Private Sector (HKIA / HKICM / HKIS)",
                "sector": "private",
            },
        ],
        "vat_standard_rate": 0,
        "currency_decimals": 2,
        "retention_percent": 10,
        "retention_limit_percent": 5,
        "levy_threshold_hkd": 3000000,
        "review_status": (
            "Statutory periods and thresholds read from the text of Cap. 652 (s.15, s.18, s.20, s.21, s.23, s.24, "
            "Sch. 4) and the levy rates from cic.hk. Retention figures and the NEC4 default are working defaults, "
            "never enforced. The zh-HK wording and the glossary are pending review by a Hong Kong quantity surveyor."
        ),
        # Ships as a preview: the wording, glossary and rates still wait for a Hong Kong review.
        "release_stage": "preview",
        "support_email": "info@datadrivenconstruction.io",
    },
)
