"""Build the ``PartnerPackManifest`` instance for the korea-kr pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="korea-kr",
    partner_name="South Korea Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for South Korean construction: KBIM classification, "
        "KS material standards, MOLIT Standard Specifications, Building Act, "
        "and KRW with VAT at 10 percent. Korean + English UI."
    ),
    default_locale="ko",
    additional_locales={},
    cwicr_regions=[
        "cwicr-ko-seoul",
    ],
    default_currency="KRW",
    default_tax_template="kr_vat_10",
    default_methodology=None,
    validation_rule_packs=[],
    # No Korean rule set exists in the engine yet.
    validation_rule_sets=[],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["residential-seoul"],
    branding=PartnerBranding(
        primary_color="#003478",  # Korean blue (Taegeukgi)
        accent_color="#C60C30",  # Korean red (Taegeukgi)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "KR",
        "country_name_en": "South Korea",
        "country_name_ko": "\ub300\ud55c\ubbfc\uad6d",
        "classification_standard": "kbim",
        "measurement_system": "metric",
        "paper_size": "A4",
        "regulator_refs": [
            "Building Act (Geonchukbeop)",
            "KS standards (Korean Industrial Standards, KATS)",
            "MOLIT Standard Specifications",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
