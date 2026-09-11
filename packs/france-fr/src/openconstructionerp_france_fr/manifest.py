"""Build the ``PartnerPackManifest`` instance for the france-fr pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="france-fr",
    partner_name="France Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for French construction: DPGF decomposition, "
        "NF DTU measurement standards, Code des marches publics, "
        "CCAG-Travaux, Loi MOP, RE 2020 environmental regulation, "
        "and EUR with TVA at 20 percent. French + English UI."
    ),
    default_locale="fr",
    additional_locales={},
    cwicr_regions=[
        "cwicr-fr-paris",
    ],
    default_currency="EUR",
    default_tax_template="fr_tva_20",
    default_methodology=None,
    validation_rule_packs=[],
    validation_rule_sets=[
        "dpgf",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["school-paris", "hospital-lyon"],
    branding=PartnerBranding(
        primary_color="#002395",  # French blue (Tricolore)
        accent_color="#ED2939",  # French red (Tricolore)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "FR",
        "country_name_en": "France",
        "country_name_fr": "France",
        "classification_standard": "dpgf",
        "measurement_system": "metric",
        "paper_size": "A4",
        "regulator_refs": [
            "Code des marches publics",
            "NF DTU series (AFNOR / CSTB)",
            "Loi MOP (Maitrise d'Ouvrage Publique)",
            "CCAG-Travaux (Cahier des Clauses Administratives Generales)",
            "RE 2020 (Reglementation Environnementale)",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
