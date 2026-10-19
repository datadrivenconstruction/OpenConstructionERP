"""Build the ``PartnerPackManifest`` instance for the belgium-be pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="belgium-be",
    partner_name="Belgium Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for the Belgian construction market: bilingual "
        "NL/FR interface support, EUR currency with 21% BTW/TVA on "
        "new-build and 6% on renovation, BB/SfB element classification, "
        "Belgian meetstaat (bestek) estimating practice."
    ),
    default_locale="nl",
    additional_locales={},
    cwicr_regions=[],
    default_currency="EUR",
    default_tax_template=None,
    default_methodology="belgium",
    validation_rule_packs=[],
    validation_rule_sets=[
        "din276",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["office-brussels", "residential-antwerp"],
    branding=PartnerBranding(
        primary_color="#000000",  # black of the Belgian tricolour
        accent_color="#FDDA24",  # yellow of the Belgian tricolour
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path=None,
    metadata={
        "country": "BE",
        "country_name_en": "Belgium",
        "country_name_nl": "Belgie",
        "country_name_fr": "Belgique",
        "classification_standard": "din276",
        "measurement_system": "metric",
        "regulator_refs": [
            "BB/SfB (Belgian SfB classification for building elements)",
            "Belgisch bestek - meetstaat (Belgian specification and measurement)",
            "Wet Overheidsopdrachten / Loi Marches Publics (Public Procurement Law)",
            "EPB/PEB (Energieprestatie Regelgeving / Performance Energetique des Batiments)",
            "NBN EN standards (Bureau voor Normalisatie, Eurocode-aligned)",
            "Woningbouwbesluit / Code du Logement (Housing Code)",
        ],
        "vat_standard_rate": 21,
        "vat_renovation_rate": 6,
        "support_email": "info@datadrivenconstruction.io",
    },
)
