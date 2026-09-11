"""Build the ``PartnerPackManifest`` instance for the germany-de pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="germany-de",
    partner_name="Germany Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "DIN 276 cost groups, VOB/C trade structure, GAEB DA XML 3.3 exchange, "
        "HOAI 2021 fee scale, BKI cost benchmarks, EUR with 19% Umsatzsteuer. "
        "German + English UI."
    ),
    default_locale="de",
    additional_locales={},
    cwicr_regions=[
        # Two German CWICR catalogues exist: Berlin and Munich. Other metros
        # (Frankfurt, Hamburg, Cologne, Stuttgart, Dusseldorf) are not yet
        # published. BKI regional factors bridge the gap for projects outside
        # Berlin and Munich.
        "cwicr-de-berlin",
        "cwicr-de-munich",
    ],
    default_currency="EUR",
    default_tax_template="de_ust_19",
    default_methodology="germany",
    validation_rule_packs=[
        # DIN 276 cost group hierarchy and completeness
        "din_276",
        # GAEB DA XML exchange phases (X81 / X83 / X84 / X86)
        "gaeb_x83_x86",
        # VOB 2019 Parts A (procurement) + B (contract) + C (ATVs, DIN 18299 ff.)
        "vob_2019",
        # HOAI 2021 Honorarordnung fee structure
        "hoai_2021_fees",
        # BKI Baukosteninformationszentrum cost benchmarks
        "bki_benchmarks",
    ],
    # The engine identifiers behind the documents above. These activate the
    # DIN 276 and GAEB rule sets that the core already ships. Without them
    # the rules stay off for this pack.
    validation_rule_sets=[
        "din276",
        "gaeb",
    ],
    default_modules=[],  # empty = show all (no module hiding)
    hidden_modules=[],
    demo_template_ids=[
        "residential-berlin",
        "office-frankfurt",
        "retail-market-heidelberg",
        "retail-market-heilbronn",
        "retail-market-karlsruhe",
    ],
    branding=PartnerBranding(
        primary_color="#000000",  # Schwarz (German flag)
        accent_color="#FFCE00",  # Gold (German flag)
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "DE",
        "country_name_en": "Germany",
        "country_name_de": "Deutschland",
        "classification_standard": "din276",
        "measurement_system": "metric",
        "regulator_refs": [
            "DIN 276:2018-12 (Kosten im Bauwesen)",
            "VOB/A 2019 (Vergabe- und Vertragsordnung, Vergabe)",
            "VOB/B 2019 (Vergabe- und Vertragsordnung, Vertragsbedingungen)",
            "VOB/C 2019 (Allgemeine Technische Vertragsbedingungen, DIN 18299 ff.)",
            "GAEB DA XML 3.3 (Datenaustausch, X81/X83/X84/X86)",
            "HOAI 2021 (Honorarordnung fuer Architekten und Ingenieure)",
            "AHO (Projektmanagement-Honorarleitfaden)",
            "BKI Baukosteninformationszentrum (Kostenbenchmarks)",
        ],
        "cwicr_regions_available": [
            "Berlin",
            "Munich",
        ],
        "cwicr_regions_planned": [
            "Frankfurt am Main",
            "Hamburg",
            "Cologne",
            "Stuttgart",
            "Dusseldorf",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
