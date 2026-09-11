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
        # One Turkish catalogue exists under this marketplace slug. It
        # resolves to TR_NATIONAL via the alias or city index. Additional
        # cities (Ankara, Izmir, Antalya) are planned but no catalogue is
        # published for them yet.
        "cwicr-tr-istanbul",
    ],
    default_currency="TRY",
    default_tax_template="tr_kdv_20",
    default_methodology="turkey",
    validation_rule_packs=[],
    # No Turkish-specific engine rule set yet. When one is built it will
    # carry rules for birim fiyat item references and pozlar numbering.
    validation_rule_sets=[],
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
