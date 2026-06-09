"""Build the ``PartnerPackManifest`` instance for the batimatech-ca pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="batimatech-ca",
    partner_name="Batimatech",
    partner_url="https://www.batimatech.com",
    pack_version="0.2.0",
    description=(
        "Pré-configuré pour les entreprises canadiennes de construction: "
        "CNB 2020, contrats CCDC, normes CSA et conformité provinciale "
        "(Québec CCQ/RBQ, Ontario OBC)."
    ),
    default_locale="fr-CA",
    additional_locales={
        "fr-CA": "locales/fr-CA.json",
        "en-CA": "locales/en-CA.json",
    },
    # NOTE: cwicr-fra-montreal is NOT yet published in the marketplace
    # (see backend/app/core/marketplace.py — only cwicr-eng-toronto exists
    # for Canada as of v5.6.0). When the FR-CA Montréal snapshot ships,
    # add "cwicr-fra-montreal" here.
    cwicr_regions=[
        "cwicr-eng-toronto",
    ],
    default_currency="CAD",
    default_tax_template="ca_gst_pst",
    validation_rule_packs=[
        "nbc_2020",
        "ccdc_2",
        "ccdc_5a",
        "ccdc_14",
        "csa_a23_1",
        "csa_a23_3",
        "csa_s16",
        "ontario_obc",
        "quebec_ccq",
    ],
    default_modules=[],   # empty = show all (Shape A, no module hiding)
    hidden_modules=[],
    demo_template_ids=["condo-toronto"],
    branding=PartnerBranding(
        primary_color="#1C9BD7",  # batimatech cyan
        accent_color="#1B3A5B",  # batimatech navy
        logo_path="logo.png",
        favicon_path="favicon.ico",
        powered_by_text="Powered by OpenConstructionERP, in partnership with Batimatech",
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "CA",
        "country_name_en": "Canada",
        "country_name_fr": "Canada",
        "regulator_refs": [
            "NBC 2020",
            "CCDC 2-2020 / 5A-2025 / 14-2013",
            "CSA A23.1 / A23.3 / S16",
            "OBC (Ontario)",
            "CCQ / RBQ (Québec)",
        ],
        "support_email": "contact@batimatech.ca",
    },
)
