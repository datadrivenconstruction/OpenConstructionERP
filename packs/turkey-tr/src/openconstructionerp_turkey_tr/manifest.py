"""Build the ``PartnerPackManifest`` instance for the turkey-tr pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="turkey-tr",
    partner_name="Turkey Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Turkish contractors, designers and public "
        "clients: Bayindirlik Bakanligi Birim Fiyat unit-price methodology, "
        "Deprem Yonetmeligi 2018 (TBDY) seismic code, Imar Kanunu zoning "
        "compliance, TSE construction standards, KDV at 20 percent, Turkish "
        "lira at two decimals."
    ),
    default_locale="tr",
    additional_locales={},
    cwicr_regions=[
        # Two different bases, not two names for one. TR_ISTANBUL is the
        # global-market catalogue priced for Istanbul; TR_NATIONAL is built
        # from the national Birim Fiyat unit-price analyses this pack is about.
        # The activation dialog offers both and the user can untick either.
        # No catalogue is published for other cities (Ankara, Izmir, Antalya).
        "cwicr-tr-istanbul",
        "cwicr-tr-national",
    ],
    default_currency="TRY",
    default_tax_template="tr_kdv_20",
    default_methodology="turkey",
    validation_rule_packs=[
        "tbdy_2018",
        "tse_standards",
        "bayindirlik_unit_prices",
        "kamu_ihale",
    ],
    # The engine rule set that reads the poz number every Turkish line is
    # priced from. It shares its name with the classification key it reads,
    # unlike Hungary, where the classification is tetelrend and the rule set
    # is hungary, so the name is checked against the registry by test rather
    # than assumed.
    validation_rule_sets=["birimfiyat"],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["mixed-use-istanbul"],
    branding=PartnerBranding(
        primary_color="#E30A17",  # Turkish red (flag crescent background)
        accent_color="#FFFFFF",  # white (flag crescent and star)
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use the default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "TR",
        "country_name_en": "Turkey",
        "country_name_tr": "Turkiye",
        "classification_standard": "birimfiyat",
        "regulator_refs": [
            "Bayindirlik Bakanligi Birim Fiyat (Ministry of Public Works unit prices)",
            "Imar Kanunu (Zoning Law No. 3194)",
            "Deprem Yonetmeligi 2018 / TBDY (Turkish Building Seismic Code 2018)",
            "TSE (Turkish Standards Institution) construction standards",
            "Kamu Ihale Kanunu (Public Procurement Law No. 4734)",
            "Yapi Denetimi Hakkinda Kanun (Building Inspection Law No. 4708)",
        ],
        "vat_standard_rate": 20,
        "currency_decimals": 2,
        "review_status": (
            "Regulatory references are drawn from public sources and are "
            "pending review by a Turkish quantity surveyor before they are "
            "relied on for a public tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
