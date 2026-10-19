"""Build the ``PartnerPackManifest`` instance for the sweden-se pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="sweden-se",
    partner_name="Sweden Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Swedish construction estimating: AMA "
        "(Allman Material- och Arbetsbeskrivning) specification system, "
        "AB 04 / ABT 06 standard contract conditions, BSAB classification, "
        "SEK currency with 25% moms. Swedish and English interface."
    ),
    default_locale="sv",
    additional_locales={},
    cwicr_regions=[
        "cwicr-se-stockholm",
    ],
    default_currency="SEK",
    default_tax_template=None,
    default_methodology="sweden",
    validation_rule_packs=[
        "ama_specification",
        "bsab_classification",
        "ab04_contract",
    ],
    validation_rule_sets=[],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=[
        "office-stockholm",
        "residential-gothenburg",
    ],
    branding=PartnerBranding(
        primary_color="#006AA7",  # Swedish blue (flag)
        accent_color="#FECC02",  # Swedish gold (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "SE",
        "country_name_en": "Sweden",
        "country_name_sv": "Sverige",
        "classification_standard": "bsab",
        "measurement_system": "metric",
        "regulator_refs": [
            "AMA (Allman Material- och Arbetsbeskrivning, specification system)",
            "AB 04 (Allmanna Bestammelser for byggnads-, anlaggnings- och installationsentreprenader)",
            "ABT 06 (Allmanna Bestammelser for totalentreprenader)",
            "BSAB (Byggandets Samordning AB, classification system)",
            "Boverkets byggregler, BBR (National Board of Housing, Building and Planning regulations)",
            "Plan- och bygglagen, PBL (Planning and Building Act)",
            "Miljoebalken (Environmental Code)",
        ],
        "vat_standard_rate": 25,
        "vat_reduced_rate": 12,
        "review_status": (
            "Classification, currency and tax references are drawn from "
            "public sources. Regulatory references are pending review by "
            "a Swedish quantity surveyor before they are relied on for a "
            "tender submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
