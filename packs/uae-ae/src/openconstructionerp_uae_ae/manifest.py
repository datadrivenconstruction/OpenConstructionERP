"""Build the ``PartnerPackManifest`` instance for the uae-ae pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="uae-ae",
    partner_name="UAE Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for contractors and consultants in the United Arab "
        "Emirates: MasterFormat classification (the predominant system in "
        "Gulf construction), AED currency with 5% VAT, Abu Dhabi Building "
        "Code and Dubai Municipality Building Code references, Civil Defense "
        "fire and life safety regulations, and Estidama Pearl Rating for "
        "sustainable development. English interface with Arabic greeting "
        "in onboarding."
    ),
    default_locale="en",
    additional_locales={},
    cwicr_regions=[
        "cwicr-ar-dubai",  # resolves to AE_DUBAI
    ],
    default_currency="AED",
    default_tax_template="ae_vat_5",
    default_methodology="uae",
    validation_rule_packs=[],
    validation_rule_sets=[
        "masterformat",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["warehouse-dubai", "tower-abudhabi"],
    branding=PartnerBranding(
        primary_color="#00732F",  # UAE green (flag)
        accent_color="#EF3340",  # UAE red (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "AE",
        "country_name_en": "United Arab Emirates",
        "country_name_ar": "\u0627\u0644\u0625\u0645\u0627\u0631\u0627\u062a \u0627\u0644\u0639\u0631\u0628\u064a\u0629 \u0627\u0644\u0645\u062a\u062d\u062f\u0629",
        "classification_standard": "masterformat",
        "regulator_refs": [
            "Abu Dhabi International Building Code (IBC-based)",
            "Dubai Municipality Building Code",
            "Civil Defense regulations (fire and life safety)",
            "Estidama Pearl Rating System (Abu Dhabi)",
        ],
        "vat_standard_rate": 5,
        "review_status": (
            "Classification, currency and tax references are drawn from "
            "public sources. Regulatory references are pending review by "
            "a UAE-based quantity surveyor before they are relied on for "
            "a tender submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
