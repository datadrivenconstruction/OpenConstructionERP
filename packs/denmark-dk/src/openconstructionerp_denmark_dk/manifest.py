"""Build the ``PartnerPackManifest`` instance for the denmark-dk pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="denmark-dk",
    partner_name="Denmark Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Danish construction estimating: V&S "
        "(Vejledende Beskrivelser) specification system, AB 18 / ABT 18 "
        "standard contract conditions, SfB / CCS classification, "
        "DKK currency with 25% moms. Danish and English interface."
    ),
    default_locale="da",
    additional_locales={},
    # No Danish base is published yet, so none is declared; Copenhagen
    # follows when it is. A declared slug that resolves to nothing was
    # listed on the activation dialog and then skipped at install.
    cwicr_regions=[],
    default_currency="DKK",
    default_tax_template="dk_moms_25",
    default_methodology="denmark",
    validation_rule_packs=[
        "vs_specification",
        "sfb_ccs_classification",
        "ab18_contract",
    ],
    validation_rule_sets=[],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=[
        "office-copenhagen",
        "residential-aarhus",
    ],
    branding=PartnerBranding(
        primary_color="#C8102E",  # Danish red (flag)
        accent_color="#FFFFFF",  # Danish white (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "DK",
        "country_name_en": "Denmark",
        "country_name_da": "Danmark",
        "classification_standard": "sfb_ccs",
        "measurement_system": "metric",
        "regulator_refs": [
            "V&S (Vejledende Beskrivelser, specification system)",
            "AB 18 (Almindelige Betingelser for arbejder og leverancer i bygge- og anlaegsvirksomhed)",
            "ABT 18 (Almindelige Betingelser for totalentreprise)",
            "SfB (Samarbetskommitten for Byggnadsfragor, classification system)",
            "CCS (Cuneco Classification System)",
            "Bygningsreglementet, BR 18 (Danish Building Regulations)",
            "Planloven (Planning Act)",
        ],
        "vat_standard_rate": 25,
        "review_status": (
            "Classification, currency and tax references are drawn from "
            "public sources. Regulatory references are pending review by "
            "a Danish quantity surveyor before they are relied on for a "
            "tender submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
