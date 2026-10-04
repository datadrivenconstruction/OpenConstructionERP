"""Build the ``PartnerPackManifest`` instance for the switzerland-ch pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="switzerland-ch",
    partner_name="Switzerland Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Swiss contractors, Bauherrenberater and "
        "Totalunternehmer: SIA 451 cost planning, BKP (Baukostenplan) "
        "classification, SIA 118 contract conditions, CRB standards, "
        "CHF with 8.1 percent MWST/TVA. Trilingual DE/FR/IT."
    ),
    default_locale="de",
    additional_locales={},
    cwicr_regions=[],
    default_currency="CHF",
    default_tax_template="ch_mwst_8_1",
    default_methodology="switzerland",
    validation_rule_packs=[
        "sia_451",
        "bkp_classification",
        "sia_118",
    ],
    # Swiss bills are coded in BKP, which has no rule set yet, so the pack runs
    # what the CH country row runs: the GAEB structure checks and no cost-group
    # code rule that a BKP bill would fail line by line.
    validation_rule_sets=["gaeb"],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=[
        "office-zurich",
        "residential-lausanne",
    ],
    branding=PartnerBranding(
        primary_color="#D52B1E",  # Swiss red (flag)
        accent_color="#FFFFFF",  # Swiss white (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "CH",
        "country_name_en": "Switzerland",
        "country_name_de": "Schweiz",
        "country_name_fr": "Suisse",
        "country_name_it": "Svizzera",
        "classification_standard": "bkp",
        "measurement_system": "metric",
        "regulator_refs": [
            "SIA 118:2013 (Allgemeine Bedingungen fuer Bauarbeiten / Conditions generales pour travaux de construction)",
            "SIA 451 (Kostenplanung im Hochbau / Planification des couts de construction)",
            "BKP Baukostenplan (CFC Code des frais de construction)",
            "CRB standards (Schweizerische Zentralstelle fuer Baurationalisierung)",
            "SIA 102:2020 (Leistungen und Honorare der Architekten)",
            "SIA 108:2020 (Leistungen und Honorare der Bauingenieure)",
            "SIA 112:2014 (Modell Bauplanung / phases de projet)",
            "BoeB / LMP (Bundesgesetz ueber das oeffentliche Beschaffungswesen)",
        ],
        "vat_standard_rate": 8.1,
        "vat_reduced_rate": 2.6,
        "vat_accommodation_rate": 3.8,
        "currency_decimals": 2,
        "review_status": (
            "Regulatory references are drawn from public sources and are "
            "pending review by a Swiss Baukostenplaner or quantity surveyor "
            "before they are relied on for a public submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
