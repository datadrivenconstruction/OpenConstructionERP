"""Build the ``PartnerPackManifest`` instance for the japan-jp pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="japan-jp",
    partner_name="Japan Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Japanese construction: Sekisan Kijun estimation "
        "standards, JASS specifications, Building Standards Act, Public Works "
        "Standard Specifications, and JPY with consumption tax at 10 percent. "
        "Japanese + English UI."
    ),
    default_locale="ja",
    additional_locales={},
    cwicr_regions=[
        "cwicr-ja-tokyo",
    ],
    default_currency="JPY",
    default_tax_template="jp_consumption_10",
    default_methodology=None,
    validation_rule_packs=[],
    # No sekisan rule set exists in the engine yet.
    validation_rule_sets=[],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["office-tokyo"],
    branding=PartnerBranding(
        primary_color="#BC002D",  # Japan red (Hinomaru)
        accent_color="#FFFFFF",
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "JP",
        "country_name_en": "Japan",
        "country_name_ja": "\u65e5\u672c",
        "classification_standard": "sekisan",
        "measurement_system": "metric",
        "paper_size": "A4",
        "regulator_refs": [
            "Building Standards Act (Kenchiku Kijun Ho)",
            "JASS (Japanese Architectural Standard Specification, AIJ)",
            "Public Works Standard Specifications (MLIT)",
            "Sekisan Kijun (Public Works Estimation Standards, MLIT)",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
