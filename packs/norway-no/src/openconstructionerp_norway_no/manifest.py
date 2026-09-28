"""Build the ``PartnerPackManifest`` instance for the norway-no pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="norway-no",
    partner_name="Norway Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Norwegian construction estimating: NS 3420 "
        "specification standard, NS 8405 / NS 8407 standard contract "
        "conditions, NS 3451 building element table classification, "
        "NOK currency with 25% MVA. Norwegian and English interface."
    ),
    # The platform ships its Norwegian (Bokmal) bundle as "no". The BCP-47
    # tag "nb" is not an offered code, so the resolver fell back to English.
    default_locale="no",
    additional_locales={},
    cwicr_regions=[
        "cwicr-no-oslo",
    ],
    default_currency="NOK",
    default_tax_template="no_mva_25",
    default_methodology="norway",
    validation_rule_packs=[
        "ns3420_specification",
        "ns3451_classification",
        "ns8405_contract",
    ],
    validation_rule_sets=[],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=[
        "office-oslo",
        "residential-bergen",
    ],
    branding=PartnerBranding(
        primary_color="#BA0C2F",  # Norwegian red (flag)
        accent_color="#00205B",  # Norwegian blue (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "NO",
        "country_name_en": "Norway",
        "country_name_nb": "Norge",
        "classification_standard": "ns3451",
        "measurement_system": "metric",
        "regulator_refs": [
            "NS 3420 (Beskrivelsestekster for bygg, anlegg og installasjoner, specification standard)",
            "NS 3451 (Bygningsdelstabell, building element table)",
            "NS 3453 (Spesifikasjon av kostnader i byggeprosjekt, cost breakdown structure)",
            "NS 8405 (Norsk bygge- og anleggskontrakt, general contractor)",
            "NS 8407 (Alminnelige kontraktsbestemmelser, design-build)",
            "TEK17 (Byggteknisk forskrift, technical building regulations)",
            "Plan- og bygningsloven (Planning and Building Act)",
        ],
        "vat_standard_rate": 25,
        "vat_reduced_rate": 15,
        "review_status": (
            "Classification, currency and tax references are drawn from "
            "public sources. Regulatory references are pending review by "
            "a Norwegian quantity surveyor before they are relied on for a "
            "tender submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
